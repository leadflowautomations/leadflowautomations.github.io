"""Lead Flow runtime hardening.
Loads before uvicorn so the complete pipeline gets resilient discovery,
contact enrichment, safe automation and durable job storage.
"""
try:
    import asyncio
    import re

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

    async def _enrich_contacts(client, rows):
        """Resolve public OSM contact tags in batches after Photon discovery.
        Photon is used for fast discovery but does not reliably expose contact tags.
        Nominatim lookup can return website/phone/email from OSM extratags in one
        request for a batch, avoiding one request per business.
        """
        wanted = {}
        for row in rows:
            match = re.match(r"osm:(node|way|relation):(.+)$", str(row.get("source_id") or ""))
            if not match:
                continue
            typ = {"node": "N", "way": "W", "relation": "R"}[match.group(1)]
            osm_id = match.group(2)
            wanted[f"{typ}{osm_id}"] = row
        if not wanted:
            return rows
        keys = list(wanted)
        for start in range(0, len(keys), 50):
            if start:
                await asyncio.sleep(1.1)
            batch = keys[start:start + 50]
            try:
                response = await client.get(
                    "https://nominatim.openstreetmap.org/lookup",
                    params={
                        "osm_ids": ",".join(batch),
                        "format": "jsonv2",
                        "addressdetails": 1,
                        "extratags": 1,
                    },
                    headers={"User-Agent": _lf.UA, "Referer": "https://leadflowautomations.github.io/"},
                )
                response.raise_for_status()
                for result in response.json():
                    typ = {"N": "node", "W": "way", "R": "relation"}.get(str(result.get("osm_type") or "")[0:1])
                    key = f"{str(result.get('osm_type') or '')}{result.get('osm_id')}"
                    # Nominatim uses node/way/relation strings; normalize to lookup keys.
                    if not typ:
                        raw = str(result.get("osm_type") or "")
                        typ = raw if raw in {"node", "way", "relation"} else None
                    if typ:
                        key = f"{'N' if typ == 'node' else 'W' if typ == 'way' else 'R'}{result.get('osm_id')}"
                    row = wanted.get(key)
                    if not row:
                        continue
                    extra = result.get("extratags") or {}
                    website = extra.get("contact:website") or extra.get("website")
                    phone = extra.get("contact:phone") or extra.get("phone")
                    email = extra.get("contact:email") or extra.get("email")
                    if website and not row.get("website"):
                        row["website"] = _lf.clean_url(website)
                    if phone and not row.get("phone"):
                        row["phone"] = _lf.clean_phone(phone)
                    if email and not row.get("email"):
                        row["email"] = _lf.clean_email(email)
            except Exception as exc:
                print(f"Lead Flow OSM contact enrichment skipped: {exc}", flush=True)
        return rows

    _original_discover = _lf.discover

    async def _discover_with_contacts(city, industry, country, job):
        rows = await _original_discover(city, industry, country, job)
        if rows:
            async with __import__("httpx").AsyncClient(timeout=_lf.TIMEOUT) as client:
                rows = await _enrich_contacts(client, rows)
        return rows

    _lf.discover = _discover_with_contacts

    from backend.fastapi.job_store import PersistentJobs
    _lf.JOBS = PersistentJobs()
    print(f"Lead Flow durable job store active: {getattr(_lf.JOBS, 'persistent', False)}", flush=True)
except Exception as exc:
    print(f"Lead Flow runtime bootstrap unavailable: {exc}", flush=True)
