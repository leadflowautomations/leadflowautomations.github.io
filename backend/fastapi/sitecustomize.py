"""Render-safe OSM discovery adapter.

Render cannot reliably reach the configured Overpass endpoints, so when the
Photon provider is enabled this module translates the existing Overpass
requests into bounded Nominatim POI searches while preserving the FastAPI
contract. Google Places is not used.

The public Nominatim service is deliberately throttled here because Lead Flow
may issue several additive discovery queries for one search. This adapter is
a compatibility/fallback layer, not a claim that the public Nominatim service
is a bulk POI database.
"""

import asyncio
import builtins
import json
import math
import os
import re
import sys
import time
from urllib.parse import unquote


if os.getenv("LEADFLOW_DISCOVERY_PROVIDER", "").strip().lower() == "photon":
    import httpx

    _original_post = httpx.AsyncClient.post
    _around_re = re.compile(r"around:(\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
    _tag_re = re.compile(r'[\"([^\"\]]+)=\"([^\"\]]+)\"]')
    _name_re = re.compile(r'[\"name\"~\"((?:\\\\.|[^\"\\\\])*)\",i\]')
    _USER_AGENT = "LeadFlowResearch/2.6 (+https://leadflowautomations.github.io/)"
    _nominatim_lock = asyncio.Lock()
    _last_nominatim_request = 0.0
    _NOMINATIM_MIN_INTERVAL = max(1.0, float(os.getenv("NOMINATIM_MIN_INTERVAL", "1.05")))

    def _decode_regex(value: str) -> str:
        return re.sub(r"\\\\(.)", r"\1", unquote(value))

    def _bbox(lat: float, lon: float, radius_m: float) -> str:
        lat_delta = radius_m / 111_000.0
        lon_scale = max(0.25, abs(math.cos(math.radians(lat))))
        lon_delta = radius_m / (111_000.0 * lon_scale)
        return f"{lon - lon_delta},{lat - lat_delta},{lon + lon_delta},{lat + lat_delta}"

    def _nominatim_to_element(place: dict) -> dict | None:
        osm_id = place.get("osm_id")
        osm_type = {"node": "node", "way": "way", "relation": "relation"}.get(place.get("osm_type"), "node")
        name = (place.get("name") or place.get("display_name", "").split(",", 1)[0]).strip()
        if not osm_id or not name:
            return None
        address = place.get("address") or {}
        extra = place.get("extratags") or {}
        tags = {
            "name": name,
            "addr:housenumber": address.get("house_number"),
            "addr:street": address.get("road"),
            "addr:city": address.get("city") or address.get("town") or address.get("village") or address.get("municipality"),
            "addr:state": address.get("state"),
            "addr:postcode": address.get("postcode"),
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
        return {
            "type": osm_type,
            "id": osm_id,
            "lat": float(place.get("lat")) if place.get("lat") else None,
            "lon": float(place.get("lon")) if place.get("lon") else None,
            "tags": tags,
        }

    async def _nominatim_request(client: httpx.AsyncClient, *, q: str, lat: float, lon: float, bbox: str) -> list[dict]:
        global _last_nominatim_request
        params = {
            "q": q,
            "format": "jsonv2",
            "limit": 40,
            "viewbox": bbox,
            "bounded": 1,
            "layer": "poi",
            "addressdetails": 1,
            "extratags": 1,
            "dedupe": 0,
        }
        async with _nominatim_lock:
            wait_for = _NOMINATIM_MIN_INTERVAL - (time.monotonic() - _last_nominatim_request)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            response = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
                headers={"User-Agent": _USER_AGENT, "Referer": "https://leadflowautomations.github.io/"},
                timeout=20,
            )
            _last_nominatim_request = time.monotonic()
        response.raise_for_status()
        return [x for x in (_nominatim_to_element(place) for place in response.json()) if x]

    async def _photon_elements(client: httpx.AsyncClient, query: str) -> list[dict]:
        match = _around_re.search(query)
        if not match:
            return []
        radius_m, lat, lon = float(match.group(1)), float(match.group(2)), float(match.group(3))
        bbox = _bbox(lat, lon, radius_m)
        tag_match = _tag_re.search(query)
        if tag_match:
            _, value = tag_match.groups()
            keyword = value.replace("_", " ")
            results = await _nominatim_request(client, q=keyword, lat=lat, lon=lon, bbox=bbox)
            if results:
                return results
        name_match = _name_re.search(query)
        if not name_match:
            return []
        keyword = _decode_regex(name_match.group(1)).strip()
        return await _nominatim_request(client, q=keyword, lat=lat, lon=lon, bbox=bbox) if keyword else []

    async def _post(self, url, *args, **kwargs):
        if "overpass" not in str(url).lower():
            return await _original_post(self, url, *args, **kwargs)
        query = kwargs.get("data") if kwargs.get("data") is not None else (args[0] if args else None)
        if not isinstance(query, str):
            return await _original_post(self, url, *args, **kwargs)
        try:
            elements = await _photon_elements(self, query)
            print(f"OSM bounded discovery adapter returned {len(elements)} elements", flush=True)
        except Exception as exc:
            print(f"OSM bounded discovery provider failed: {exc}", flush=True)
            elements = []
        payload = {"version": 0.6, "generator": "LeadFlow bounded Nominatim OSM adapter", "elements": elements}
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode(),
            request=httpx.Request("POST", str(url)),
        )

    httpx.AsyncClient.post = _post


# Lead Flow v3 currently computes score immediately before calling automation(),
# but stores that score on the candidate only afterwards. Patch the imported
# module at import time so the existing pipeline remains safe without changing
# discovery or contact semantics. The wrapper derives the same evidence-based
# score when the field is not present, then delegates to the original function.
_original_import = builtins.__import__


def _leadflow_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _original_import(name, globals, locals, fromlist, level)
    if name == "backend.fastapi.leadflow_v3":
        target = sys.modules.get(name)
        if target is not None and not getattr(target, "_leadflow_automation_hotfix", False):
            original_automation = target.automation

            def safe_automation(candidate):
                if "score" not in candidate:
                    score_value, _, _ = target.score(candidate, candidate.get("signals", {}))
                    candidate = dict(candidate)
                    candidate["score"] = score_value
                return original_automation(candidate)

            target.automation = safe_automation
            target._leadflow_automation_hotfix = True
            print("Lead Flow v3 automation hotfix active", flush=True)
    return module


builtins.__import__ = _leadflow_import
