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
    return f'[out:json][timeout:30];({clauses});out center tags;'


def _row(lf, element: dict[str, Any], industry: str) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or tags.get("operator") or "").strip()
    if not name:
        return None
    center = element.get("center") or {}
    lat = element.get("lat") if element.get("lat") is not None else center.get("lat")
    lon = element.get("lon") if element.get("lon") is not None else center.get("lon")
    address_parts = [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city") or tags.get("addr:suburb"), tags.get("addr:state"), tags.get("addr:postcode"), tags.get("addr:country")]
    address = ", ".join(str(x) for x in address_parts if x) or None
    website = tags.get("contact:website") or tags.get("website")
    phone = tags.get("contact:phone") or tags.get("phone")
    email = tags.get("contact:email") or tags.get("email")
    return {"source_id": f"osm:{element.get('type')}:{element.get('id')}", "name": name, "address": address, "lat": lat, "lon": lon, "website": lf.clean_url(website), "phone": lf.clean_phone(phone), "email": lf.clean_email(email), "source": "OpenStreetMap/Overpass", "industry": industry}


async def _resolve_center(lf, client, city: str, country: str):
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
    async with httpx.AsyncClient(timeout=40.0) as client:
        center = await _resolve_center(lf, client, city, country)
        lat, lon = center
        lat_span = 0.35
        lon_span = 0.45 if abs(lat) > 20 else 0.35
        south, north = lat - lat_span, lat + lat_span
        west, east = lon - lon_span, lon + lon_span
        grid_rows, grid_cols = 5, 5
        cells = []
        for gy in range(grid_rows):
            cell_south = south + (north - south) * gy / grid_rows
            cell_north = south + (north - south) * (gy + 1) / grid_rows
            for gx in range(grid_cols):
                cell_west = west + (east - west) * gx / grid_cols
                cell_east = west + (east - west) * (gx + 1) / grid_cols
                cells.append((cell_south, cell_west, cell_north, cell_east))
        job.update(stage="collect", message=f"Collecting mapped businesses across {len(cells)} search areas…", collection_queries=len(cells), collection_completed=0, updated_at=time.time())
        rows: list[dict[str, Any]] = []
        endpoint_index = 0
        for completed, (cell_south, cell_west, cell_north, cell_east) in enumerate(cells, 1):
            query = _query(tags, cell_south, cell_west, cell_north, cell_east)
            payload = None
            attempts = 0
            last_error = None
            while attempts < len(OVERPASS_ENDPOINTS):
                endpoint = OVERPASS_ENDPOINTS[(endpoint_index + attempts) % len(OVERPASS_ENDPOINTS)]
                try:
                    response = await client.post(endpoint, data={"data": query}, headers={"User-Agent": lf.UA, "Referer": "https://leadflowautomations.github.io/"})
                    response.raise_for_status()
                    candidate = response.json()
                    if isinstance(candidate, dict) and "elements" in candidate:
                        payload = candidate
                        endpoint_index = (endpoint_index + attempts) % len(OVERPASS_ENDPOINTS)
                        break
                except Exception as exc:
                    last_error = str(exc)[:250]
                    attempts += 1
                    job["errors"] += 1
                    job["last_error"] = f"Overpass: {last_error}"
                    await asyncio.sleep(min(1.5, 0.25 * attempts))
            if payload:
                for element in payload.get("elements", []):
                    item = _row(lf, element, industry)
                    if item:
                        rows.append(item)
            elif last_error:
                print(f"Lead Flow Overpass cell {completed} failed: {last_error}", flush=True)
            unique = lf.dedupe(rows)
            job.update(collection_completed=completed, discovered=len(unique), updated_at=time.time())
        rows = lf.dedupe(rows)
        if rows:
            job.update(discovered=len(rows), collection_completed=len(cells), updated_at=time.time())
            return rows
        print("Lead Flow exhaustive Overpass returned no rows; using Photon/Nominatim fallback", flush=True)
        return await fallback(city, industry, country, job)
