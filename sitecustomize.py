"""Runtime bootstrap for Lead Flow v3.
Loaded automatically by Python before uvicorn imports the ASGI module.
"""
try:
    import asyncio

    from backend.fastapi import leadflow_v3 as _lf

    def _safe_automation(item):
        score = int(item.get("score") or 0)
        ready = bool(item.get("verified_business") and (item.get("phone") or item.get("email")))
        if score >= 75 and ready:
            action = "PRIORITY_OUTREACH"
        elif score >= 55 and ready:
            action = "OUTREACH"
        elif score >= 35:
            action = "RESEARCH_MORE"
        else:
            action = "NURTURE"
        return {
            "action": action,
            "outreach_ready": ready,
            "next_action": "Contact using verified public channel" if ready else "Find an additional public contact source",
            "reason": "High confirmed opportunity gaps with verified business identity" if ready and score >= 55 else "Needs additional evidence before outreach",
        }

    _lf.automation = _safe_automation

    async def _photon_geocode(client, city, country):
        response = await client.get(
            "https://photon.komoot.io/api/",
            params={"q": f"{city}, {country}", "limit": 1},
            headers={"User-Agent": _lf.UA},
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        if not features:
            return None
        coords = features[0].get("geometry", {}).get("coordinates", [])
        return (float(coords[1]), float(coords[0])) if len(coords) >= 2 else None

    async def _photon_search(client, query, lat, lon, delta):
        await asyncio.sleep(0.25)
        half = delta / 2
        response = await client.get(
            "https://photon.komoot.io/api/",
            params={
                "q": query,
                "limit": 40,
                "bbox": f"{lon-half},{lat-half},{lon+half},{lat+half}",
            },
            headers={"User-Agent": _lf.UA, "Referer": "https://leadflowautomations.github.io/"},
        )
        response.raise_for_status()
        converted = []
        for feature in response.json().get("features", []):
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            name = (props.get("name") or props.get("street") or "").strip()
            if not name:
                continue
            converted.append({
                "osm_type": props.get("osm_type"),
                "osm_id": props.get("osm_id"),
                "name": name,
                "display_name": ", ".join(str(props.get(k)) for k in ("name", "street", "city", "state", "postcode", "country") if props.get(k)),
                "lat": str(coords[1]) if len(coords) >= 2 else None,
                "lon": str(coords[0]) if len(coords) >= 2 else None,
                "address": {
                    "house_number": props.get("housenumber"),
                    "road": props.get("street"),
                    "city": props.get("city") or props.get("locality"),
                    "state": props.get("state"),
                    "postcode": props.get("postcode"),
                },
                "extratags": {},
            })
        return converted

    _original_geocode = _lf.geocode
    _original_search = _lf.nominatim_search

    async def _resilient_geocode(client, city, country):
        try:
            result = await _photon_geocode(client, city, country)
            if result:
                return result
        except Exception as photon_exc:
            print(f"Lead Flow Photon geocode fallback: {photon_exc}", flush=True)
        return await _original_geocode(client, city, country)

    async def _resilient_search(client, query, lat, lon, delta):
        try:
            return await _photon_search(client, query, lat, lon, delta)
        except Exception as photon_exc:
            print(f"Lead Flow Photon search fallback: {photon_exc}", flush=True)
            return await _original_search(client, query, lat, lon, delta)

    _lf.geocode = _resilient_geocode
    _lf.nominatim_search = _resilient_search

    from backend.fastapi.job_store import PersistentJobs

    _lf.JOBS = PersistentJobs()
    print(
        f"Lead Flow durable job store active: {getattr(_lf.JOBS, 'persistent', False)}",
        flush=True,
    )
except Exception as exc:
    print(f"Lead Flow runtime bootstrap unavailable: {exc}", flush=True)
