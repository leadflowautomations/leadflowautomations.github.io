import asyncio
import time
from typing import Any

import httpx


OVERPASS_ENDPOINTS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]

INDUSTRY_TAGS = {
    "real estate": [("office", "estate_agent"), ("office", "property_management"), ("shop", "estate_agent"), ("shop", "condo")],
    "law": [("office", "lawyer")],
    "dentist": [("amenity", "dentist")],
    "restaurant": [("amenity", "restaurant"), ("amenity", "cafe")],
    "salon": [("shop", "hairdresser"), ("shop", "beauty")],
    "auto repair": [("shop", "car_repair"), ("craft", "car_repair")],
}


def _query(tags: list[tuple[str, str]], south: float, west: float, north: float, east: float) -> str:
    clauses = "\n".join(f'nwr["{key}"="{value}"]({south},{west},{north},{east});' for key, value in tags)
    return f'[out:json][timeout:45];({clauses});out center tags;'


def _row(lf, element: dict[str, Any], industry: str) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or tags.get("operator") or "").strip()
    if not name:
        return None
    center = element.get("center") or {}
    lat = element.get("lat") if element.get("lat") is not None else center.get("lat")
    lon = element.get("lon") if element.get("lon") is not None else center.get("lon")
    address_parts = [
        tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city") or tags.get("addr:suburb"),
        tags.get("addr:state"), tags.get("addr:postcode"), tags.get("addr:country"),
    ]
    address = ", ".join(str(x) for x in address_parts if x) or None
    website = tags.get("contact:website") or tags.get("website")
    phone = tags.get("contact:phone") or tags.get("phone")
    email = tags.get("contact:email") or tags.get("email")
    return {
        "source_id": f"osm:{element.get('type')}:{element.get('id')}",
        "name": name,
        "address": address,
        "lat": lat,
        "lon": lon,
        "website": lf.clean_url(website),
        "phone": lf.clean_phone(phone),
        "email": lf.clean_email(email),
        "source": "OpenStreetMap/Overpass",
        "industry": industry,
    }


async def discover_exhaustive(lf, city: str, industry: str, country: str, job: dict[str, Any], fallback):
    tags = INDUSTRY_TAGS.get(industry.lower().strip())
    if not tags:
        return await fallback(city, industry, country, job)

    async with httpx.AsyncClient(timeout=55.0) as client:
        center = await lf.geocode(client, city, country)
        if not center:
            return []
        lat, lon = center
        # Search a generous city/metro box instead of returning only the first ranked POIs.
        lat_span = 0.35
        lon_span = 0.45 if abs(lat) > 20 else 0.35
        south, north = lat - lat_span, lat + lat_span
        west, east = lon - lon_span, lon + lon_span
        query = _query(tags, south, west, north, east)
        job.update(stage="collect", message="Collecting all matching mapped businesses in the search area…", collection_queries=len(OVERPASS_ENDPOINTS), collection_completed=0, updated_at=time.time())
        data = None
        last_error = None
        for index, endpoint in enumerate(OVERPASS_ENDPOINTS, 1):
            try:
                response = await client.post(endpoint, data={"data": query}, headers={"User-Agent": lf.UA, "Referer": "https://leadflowautomations.github.io/"})
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and "elements" in payload:
                    data = payload
                    job.update(collection_completed=index, updated_at=time.time())
                    break
            except Exception as exc:
                last_error = str(exc)[:250]
                job["errors"] += 1
                job["last_error"] = f"Overpass: {last_error}"
                job.update(collection_completed=index, updated_at=time.time())
                await asyncio.sleep(min(2.0, 0.5 * index))
        if data is None:
            print(f"Lead Flow exhaustive Overpass failed; using Photon/Nominatim fallback: {last_error}", flush=True)
            return await fallback(city, industry, country, job)

        rows = []
        for element in data.get("elements", []):
            item = _row(lf, element, industry)
            if item:
                rows.append(item)
        rows = lf.dedupe(rows)
        job.update(discovered=len(rows), collection_completed=len(OVERPASS_ENDPOINTS), updated_at=time.time())
        return rows
