"""Render-safe OSM discovery adapter.

Render cannot reliably reach the configured Overpass endpoints, so when the
Photon provider is enabled this module translates the existing Overpass
requests into Photon forward-search requests while preserving the FastAPI
contract. Google Places is not used.
"""

import json
import math
import os
import re
from urllib.parse import unquote


if os.getenv("LEADFLOW_DISCOVERY_PROVIDER", "").strip().lower() == "photon":
    import httpx

    _original_post = httpx.AsyncClient.post
    _around_re = re.compile(r"around:(\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
    _tag_re = re.compile(r'\["([^"\]]+)"="([^"\]]+)"\]')
    _name_re = re.compile(r'\["name"~"((?:\\.|[^"\\])*)",i\]')
    _USER_AGENT = "LeadFlowResearch/2.5 (+https://leadflowautomations.github.io/)"

    def _decode_regex(value: str) -> str:
        return re.sub(r"\\(.)", r"\1", unquote(value))

    def _bbox(lat: float, lon: float, radius_m: float) -> str:
        lat_delta = radius_m / 111_000.0
        lon_scale = max(0.25, abs(math.cos(math.radians(lat))))
        lon_delta = radius_m / (111_000.0 * lon_scale)
        return f"{lon - lon_delta},{lat - lat_delta},{lon + lon_delta},{lat + lat_delta}"

    def _feature_to_element(feature: dict) -> dict | None:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        name = (properties.get("name") or "").strip()
        if len(coordinates) < 2 or not name:
            return None
        extra = properties.get("extra") or {}
        tags = {
            "name": name,
            "addr:housenumber": properties.get("housenumber"),
            "addr:street": properties.get("street"),
            "addr:city": properties.get("city"),
            "addr:state": properties.get("state"),
            "addr:postcode": properties.get("postcode"),
            "contact:phone": extra.get("phone") or extra.get("contact:phone"),
            "phone": extra.get("phone"),
            "contact:email": extra.get("email") or extra.get("contact:email"),
            "email": extra.get("email"),
            "contact:website": extra.get("website") or extra.get("contact:website"),
            "website": extra.get("website"),
            "url": extra.get("url"),
            "contact:facebook": extra.get("contact:facebook") or extra.get("facebook"),
            "contact:instagram": extra.get("contact:instagram") or extra.get("instagram"),
            "contact:linkedin": extra.get("contact:linkedin") or extra.get("linkedin"),
        }
        tags = {k: v for k, v in tags.items() if v}
        osm_type = {"N": "node", "W": "way", "R": "relation"}.get(properties.get("osm_type"), "node")
        return {"type": osm_type, "id": properties.get("osm_id"), "lat": coordinates[1], "lon": coordinates[0], "tags": tags}

    async def _photon_request(client: httpx.AsyncClient, *, q: str, lat: float, lon: float, bbox: str, osm_tag: str | None = None) -> list[dict]:
        params = {"q": q, "lat": lat, "lon": lon, "limit": 50, "dedupe": 0, "bbox": bbox, "location_bias_scale": 0.1}
        if osm_tag:
            params["osm_tag"] = osm_tag
        response = await client.get("https://photon.komoot.io/api/", params=params, headers={"User-Agent": _USER_AGENT, "Referer": "https://leadflowautomations.github.io/"}, timeout=15)
        response.raise_for_status()
        return [x for x in (_feature_to_element(feature) for feature in response.json().get("features", [])) if x]

    async def _photon_elements(client: httpx.AsyncClient, query: str) -> list[dict]:
        match = _around_re.search(query)
        if not match:
            return []
        radius_m, lat, lon = float(match.group(1)), float(match.group(2)), float(match.group(3))
        bbox = _bbox(lat, lon, radius_m)
        tag_match = _tag_re.search(query)
        if tag_match:
            key, value = tag_match.groups()
            keyword = value.replace("_", " ")
            results = await _photon_request(client, q=keyword, lat=lat, lon=lon, bbox=bbox, osm_tag=f"{key}:{value}")
            if not results:
                results = await _photon_request(client, q=keyword, lat=lat, lon=lon, bbox=bbox)
            return results
        name_match = _name_re.search(query)
        if not name_match:
            return []
        keyword = _decode_regex(name_match.group(1)).strip()
        return await _photon_request(client, q=keyword, lat=lat, lon=lon, bbox=bbox) if keyword else []

    async def _post(self, url, *args, **kwargs):
        if "overpass" not in str(url).lower():
            return await _original_post(self, url, *args, **kwargs)
        query = kwargs.get("data") if kwargs.get("data") is not None else (args[0] if args else None)
        if not isinstance(query, str):
            return await _original_post(self, url, *args, **kwargs)
        try:
            elements = await _photon_elements(self, query)
            print(f"Photon discovery adapter returned {len(elements)} elements", flush=True)
        except Exception as exc:
            print(f"Photon discovery provider failed: {exc}", flush=True)
            elements = []
        payload = {"version": 0.6, "generator": "LeadFlow Photon OSM adapter", "elements": elements}
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(payload).encode(), request=httpx.Request("POST", str(url)))

    httpx.AsyncClient.post = _post
