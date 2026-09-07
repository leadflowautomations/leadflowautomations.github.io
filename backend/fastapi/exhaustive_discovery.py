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


def _query(tags, south, west, north, east):
    clauses = "\n".join(f'nwr["{key}"="{value}"]({south},{west},{north},{east});' for key, value in tags)
    return f'[out:json][timeout:45];({clauses});out center tags;'


def _row(lf, element: dict[str, Any], industry: str):
    tags = element.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or tags.get("operator") or "").strip()
    if not name:
        return None
    center = element.get("center") or {}
    lat = element.get("lat") if element.get("lat") is not None else center.get("lat")
    lon = element.get("lon") if element.get("lon") is not None else center.get("lon")
    address_parts = [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city") or tags.get("addr:suburb"), tags.get("addr:state"), tags.get("addr:postcode"), tags.get("addr:country")]
    address = ", ".join(str(x) for x in address_parts if x) or None
    return {"source_id": f"osm:{element.get('type')}:{element.get('id')}", "name": name, "address": address, "lat": lat, "lon": lon, "website": lf.clean_url(tags.get("contact:website") or tags.get("website")), "phone": lf.clean_phone(tags.get("contact:phone") or tags.get("phone")), "email": lf.clean_email(tags.get("contact:email") or tags.get("email")), "source": "OpenStreetMap/Overpass", "industry": industry}


async def _resolve_center(lf, client: httpx.AsyncClient, city: str, country: str):
    last_error = None
    for attempt in range(3):
        try:
            center = await lf.geocode(client, city, country)
            if center:
                return center
            last_error = "geocoder returned no result"
        except Exception as exc:
            last_error = str(exc)[:300]
        if attempt < 2:
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Unable to locate {city}, {country}: {last_error or 'unknown geocoding error'}")


async def discover_exhaustive(lf, city: str, industry: str, country: str, job: dict[str, Any], fallback):
    tags = INDUSTRY_TAGS.get(industry.lower().strip())
    if not tags:
        return await fallback(city, industry, country, job)
    async with httpx.AsyncClient(timeout=50.0) as client:
        lat, lon = await _resolve_center(lf, client, city, country)
        lat_span = 0.35
        lon_span = 0.45 if abs(lat) > 20 else 0.35
        pending = [(lat - lat_span, lon - lon_span, lat + lat_span, lon + lon_span, 0)]
        completed = 0
        rows: list[dict[str, Any]] = []
        job.update(stage="collect", message="Scanning the search area for mapped businesses…", collection_queries=None, collection_completed=0, updated_at=time.time())

        while pending:
            south, west, north, east, depth = pending.pop(0)
            payload = None
            last_error = None
            for offset, endpoint in enumerate(OVERPASS_ENDPOINTS):
                try:
                    response = await client.post(endpoint, data={"data": _query(tags, south, west, north, east)}, headers={"User-Agent": lf.UA, "Referer": "https://leadflowautomations.github.io/"})
                    response.raise_for_status()
                    candidate = response.json()
                    if isinstance(candidate, dict) and "elements" in candidate:
                        payload = candidate
                        break
                except Exception as exc:
                    last_error = str(exc)[:250]
                    job["errors"] += 1
                    job["last_error"] = f"Overpass: {last_error}"
                    await asyncio.sleep(min(1.25, 0.2 * (offset + 1)))

            if payload is not None:
                for element in payload.get("elements", []):
                    item = _row(lf, element, industry)
                    if item:
                        rows.append(item)
            elif depth < 4:
                mid_lat = (south + north) / 2
                mid_lon = (west + east) / 2
                pending.extend([
                    (south, west, mid_lat, mid_lon, depth + 1),
                    (south, mid_lon, mid_lat, east, depth + 1),
                    (mid_lat, west, north, mid_lon, depth + 1),
                    (mid_lat, mid_lon, north, east, depth + 1),
                ])
            elif last_error:
                print(f"Lead Flow Overpass area exhausted: {last_error}", flush=True)

            completed += 1
            unique = lf.dedupe(rows)
            job.update(collection_completed=completed, discovered=len(unique), updated_at=time.time())

        rows = lf.dedupe(rows)
        if rows:
            job.update(discovered=len(rows), updated_at=time.time())
            return rows
        print("Lead Flow exhaustive discovery returned no rows; using fallback discovery", flush=True)
        return await fallback(city, industry, country, job)
