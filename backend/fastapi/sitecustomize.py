"""Render-safe OSM discovery adapter.

When LEADFLOW_DISCOVERY_PROVIDER=photon, translate the existing Overpass POST
queries into Photon OSM searches. This keeps the discovery contract unchanged
for the FastAPI application while avoiding the outbound Overpass networking
failure observed on the Render instance.

Photon is an OSM-derived provider; Google Places is not used.
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
    _USER_AGENT = "LeadFlowResearch/2.4 (+https://leadflowautomations.github.io/)"

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
        if len(coordinates) < 2 or not properties.get("name"):
            return None
        extra = properties.get("extra") or {}
        tags = {
            "name": properties.get("name"),
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

    async def _photon_elements(client: httpx.AsyncClient, query: str) -> list[dict]:
        match = _around_re.search(query)
        if not match:
            return []
        radius_m = float(match.group(1))
        lat = float(match.group(2))
        lon = float(match.group(3))
        common = {"lat": lat, "lon": lon, "limit": 100, "dedupe": 1}
        headers = {"User-Agent": _USER_AGENT, "Referer": "https://leadflowautomations.github.io/"}

        tag_match = _tag_re.search(query)
        if tag_match:
            key, value = tag_match.groups()
            response = await client.get(
                "https://photon.komoot.io/reverse",
                params={**common, "radius": max(1, min(5000, radius_m / 1000.0)), "osm_tag": f"{key}:{value}"},
                headers=headers,
                timeout=15,
            )
        else:
            name_match = _name_re.search(query)
            if not name_match:
                return []
            keyword = _decode_regex(name_match.group(1))
            response = await client.get(
                "https://photon.komoot.io/api/",
                params={
                    **common,
                    "q": keyword,
                    "zoom": 12,
                    "location_bias_scale": 0.2,
                    "bbox": _bbox(lat, lon, radius_m),
                },
                headers=headers,
                timeout=15,
            )
        response.raise_for_status()
        payload = response.json()
        return [x for x in (_feature_to_element(feature) for feature in payload.get("features", [])) if x]

    async def _post(self, url, *args, **kwargs):
        if "overpass" not in str(url).lower():
            return await _original_post(self, url, *args, **kwargs)
        query = kwargs.get("data")
        if query is None and args:
            query = args[0]
        if not isinstance(query, str):
            return await _original_post(self, url, *args, **kwargs)
        elements = await _photon_elements(self, query)
        payload = {"version": 0.6, "generator": "LeadFlow Photon OSM adapter", "elements": elements}
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode("utf-8"),
            request=httpx.Request("POST", str(url)),
        )

    httpx.AsyncClient.post = _post
