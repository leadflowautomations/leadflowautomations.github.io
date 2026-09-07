"""Lead Flow runtime hardening."""
try:
    import asyncio
    import re
    import httpx
    from backend.fastapi import leadflow_v3 as _lf

    def _safe_automation(item):
        score = int(item.get("score") or 0)
        ready = bool(item.get("verified_business") and (item.get("phone") or item.get("email")))
        action = "PRIORITY_OUTREACH" if score >= 75 and ready else "OUTREACH" if score >= 55 and ready else "RESEARCH_MORE" if score >= 35 else "NURTURE"
        return {"action": action, "outreach_ready": ready, "next_action": "Contact using verified public channel" if ready else "Find an additional public contact source", "reason": "High confirmed opportunity gaps with verified business identity" if ready and score >= 55 else "Needs additional evidence before outreach"}
    _lf.automation = _safe_automation

    async def _photon_geocode(client, city, country):
        r = await client.get("https://photon.komoot.io/api/", params={"q": f"{city}, {country}", "limit": 1}, headers={"User-Agent": _lf.UA})
        r.raise_for_status()
        features = r.json().get("features", [])
        if not features: return None
        c = features[0].get("geometry", {}).get("coordinates", [])
        return (float(c[1]), float(c[0])) if len(c) >= 2 else None

    async def _photon_search(client, query, lat, lon, delta):
        await asyncio.sleep(0.25)
        half = delta / 2
        r = await client.get("https://photon.komoot.io/api/", params={"q": query, "limit": 40, "bbox": f"{lon-half},{lat-half},{lon+half},{lat+half}", "dedupe": 0}, headers={"User-Agent": _lf.UA, "Referer": "https://leadflowautomations.github.io/"})
        r.raise_for_status()
        converted = []
        rejected_keys = {"place", "highway", "boundary", "natural", "landuse", "waterway", "building"}
        business_keys = {"office", "shop", "amenity", "craft", "healthcare", "tourism", "leisure", "club", "man_made"}
        for feature in r.json().get("features", []):
            p = feature.get("properties") or {}
            c = (feature.get("geometry") or {}).get("coordinates") or []
            name = (p.get("name") or "").strip()
            osm_key = str(p.get("osm_key") or "").lower()
            if not name or osm_key in rejected_keys or osm_key not in business_keys:
                continue
            extra = p.get("extra") or {}
            converted.append({
                "osm_type": {"N":"node","W":"way","R":"relation","node":"node","way":"way","relation":"relation"}.get(str(p.get("osm_type") or ""), p.get("osm_type")),
                "osm_id": p.get("osm_id"),
                "name": name,
                "display_name": ", ".join(str(p.get(k)) for k in ("name","street","city","state","postcode","country") if p.get(k)),
                "lat": str(c[1]) if len(c) >= 2 else None,
                "lon": str(c[0]) if len(c) >= 2 else None,
                "address": {"house_number":p.get("housenumber"),"road":p.get("street"),"city":p.get("city") or p.get("locality"),"state":p.get("state"),"postcode":p.get("postcode")},
                "extratags": extra,
            })
        return converted

    _original_geocode = _lf.geocode
    _original_search = _lf.nominatim_search
    async def _resilient_geocode(client, city, country):
        try:
            result = await _photon_geocode(client, city, country)
            if result: return result
        except Exception as exc:
            print(f"Lead Flow Photon geocode fallback: {exc}", flush=True)
        return await _original_geocode(client, city, country)
    async def _resilient_search(client, query, lat, lon, delta):
        try: return await _photon_search(client, query, lat, lon, delta)
        except Exception as exc:
            print(f"Lead Flow Photon search fallback: {exc}", flush=True)
            return await _original_search(client, query, lat, lon, delta)
    _lf.geocode = _resilient_geocode
    _lf.nominatim_search = _resilient_search

    async def _enrich_contacts(client, rows):
        wanted = {}
        for row in rows:
            m = re.match(r"osm:(node|way|relation):(.+)$", str(row.get("source_id") or ""))
            if m:
                wanted[{"node":"N","way":"W","relation":"R"}[m.group(1)] + m.group(2)] = row
        if not wanted: return rows
        keys = list(wanted)
        for start in range(0, len(keys), 50):
            if start: await asyncio.sleep(1.1)
            try:
                r = await client.get("https://nominatim.openstreetmap.org/lookup", params={"osm_ids": ",".join(keys[start:start+50]), "format":"jsonv2", "addressdetails":1, "extratags":1}, headers={"User-Agent":_lf.UA, "Referer":"https://leadflowautomations.github.io/"})
                r.raise_for_status()
                for result in r.json():
                    raw = str(result.get("osm_type") or "")
                    prefix = {"node":"N","way":"W","relation":"R","N":"N","W":"W","R":"R"}.get(raw)
                    row = wanted.get((prefix or "") + str(result.get("osm_id"))) if prefix else None
                    if not row: continue
                    extra = result.get("extratags") or {}
                    website = extra.get("contact:website") or extra.get("website")
                    phone = extra.get("contact:phone") or extra.get("phone")
                    email = extra.get("contact:email") or extra.get("email")
                    if website and not row.get("website"): row["website"] = _lf.clean_url(website)
                    if phone and not row.get("phone"): row["phone"] = _lf.clean_phone(phone)
                    if email and not row.get("email"): row["email"] = _lf.clean_email(email)
            except Exception as exc:
                print(f"Lead Flow OSM contact enrichment skipped: {exc}", flush=True)
        return rows

    _original_discover = _lf.discover
    async def _discover_with_contacts(city, industry, country, job):
        rows = await _original_discover(city, industry, country, job)
        if rows:
            async with httpx.AsyncClient(timeout=_lf.TIMEOUT) as client:
                rows = await _enrich_contacts(client, rows)
        return rows
    _lf.discover = _discover_with_contacts

    from backend.fastapi.job_store import PersistentJobs
    _lf.JOBS = PersistentJobs()
    print(f"Lead Flow durable job store active: {getattr(_lf.JOBS, 'persistent', False)}", flush=True)
except Exception as exc:
    print(f"Lead Flow runtime bootstrap unavailable: {exc}", flush=True)
