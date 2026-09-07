"""Lead Flow runtime hardening."""
try:
    import asyncio
    import re
    import json
    import httpx
    from urllib.parse import urlparse, urljoin
    from bs4 import BeautifulSoup
    from backend.fastapi import leadflow_v3 as _lf
    from backend.fastapi.exhaustive_discovery import discover_exhaustive

    def _safe_automation(item):
        score = int(item.get("score") or 0)
        signals = item.get("signals") or {}
        verified = bool(item.get("verified_business"))
        ready = bool(verified and (item.get("phone") or item.get("email") or signals.get("lead_form") or signals.get("booking")))
        action = "PRIORITY_OUTREACH" if score >= 75 and ready else "OUTREACH" if score >= 55 and ready else "RESEARCH_MORE" if score >= 35 else "NURTURE"
        if item.get("phone") or item.get("email"):
            next_action = "Contact using verified public phone or email"
        elif signals.get("lead_form") or signals.get("booking"):
            next_action = "Contact using the verified business website"
        else:
            next_action = "Find an additional public contact source"
        return {"action": action, "outreach_ready": ready, "next_action": next_action, "reason": "High confirmed opportunity gaps with a verified public contact channel" if ready and score >= 55 else "Needs additional evidence before outreach"}
    _lf.automation = _safe_automation

    async def _open_meteo_geocode(client, city, country):
        r = await client.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 10, "language": "en", "format": "json"}, headers={"User-Agent": _lf.UA})
        r.raise_for_status()
        results = r.json().get("results", [])
        country_low = country.lower().strip()
        for item in results:
            if str(item.get("country", "")).lower() == country_low or str(item.get("country_code", "")).lower() == country_low:
                return (float(item["latitude"]), float(item["longitude"]))
        if results:
            return (float(results[0]["latitude"]), float(results[0]["longitude"]))
        return None

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
            if not name or osm_key in rejected_keys or osm_key not in business_keys: continue
            extra = p.get("extra") or {}
            converted.append({"osm_type": {"N":"node","W":"way","R":"relation","node":"node","way":"way","relation":"relation"}.get(str(p.get("osm_type") or ""), p.get("osm_type")), "osm_id": p.get("osm_id"), "name": name, "display_name": ", ".join(str(p.get(k)) for k in ("name","street","city","state","postcode","country") if p.get(k)), "lat": str(c[1]) if len(c)>=2 else None, "lon": str(c[0]) if len(c)>=2 else None, "address": {"house_number":p.get("housenumber"),"road":p.get("street"),"city":p.get("city") or p.get("locality"),"state":p.get("state"),"postcode":p.get("postcode")}, "extratags": extra})
        return converted

    _original_geocode = _lf.geocode
    _original_search = _lf.nominatim_search
    async def _resilient_geocode(client, city, country):
        try:
            result = await _open_meteo_geocode(client, city, country)
            if result: return result
        except Exception as exc: print(f"Lead Flow Open-Meteo geocode fallback: {exc}", flush=True)
        try:
            result = await _photon_geocode(client, city, country)
            if result: return result
        except Exception as exc: print(f"Lead Flow Photon geocode fallback: {exc}", flush=True)
        return await _original_geocode(client, city, country)
    async def _resilient_search(client, query, lat, lon, delta):
        try: return await _photon_search(client, query, lat, lon, delta)
        except Exception as exc:
            print(f"Lead Flow Photon search fallback: {exc}", flush=True)
            return await _original_search(client, query, lat, lon, delta)
    _lf.geocode = _resilient_geocode
    _lf.nominatim_search = _resilient_search

    _original_site_signals = _lf.site_signals
    def _stronger_site_signals(url, html, status, seconds, name):
        signals = _original_site_signals(url, html, status, seconds, name)
        if signals.get("business_match"): return signals
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        meta = soup.find("meta", attrs={"name": re.compile("description", re.I)})
        desc = str(meta.get("content") or "") if meta else ""
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        name_tokens = {x for x in re.findall(r"[a-z0-9]+", name.lower()) if len(x) > 3}
        host_tokens = set(re.findall(r"[a-z0-9]+", host.split(".")[0]))
        page_tokens = set(re.findall(r"[a-z0-9]+", (title + " " + desc).lower()))
        if len(name_tokens & host_tokens) >= 1 and len(name_tokens & page_tokens) >= 1:
            signals["business_match"] = True
            signals["identity_basis"] = "business name/domain/title correlation"
        return signals
    _lf.site_signals = _stronger_site_signals

    async def _broader_find_contacts(client, website, name, home_html):
        base_host = (urlparse(website).hostname or "").lower().removeprefix("www.")
        queue = [website] + [urljoin(website + "/", path) for path in ["contact", "contact-us", "contactus", "about", "about-us", "get-in-touch", "team", "agents", "our-team"]]
        found = []
        seen = set()
        scanned = set()
        while queue and len(scanned) < 25:
            url = queue.pop(0)
            if url in scanned: continue
            scanned.add(url)
            try:
                if url == website and home_html:
                    html, final_url, status = home_html, website, 200
                else:
                    response = await client.get(url, follow_redirects=True, headers={"User-Agent": _lf.UA})
                    html, final_url, status = response.text[:1_500_000], str(response.url), response.status_code
                if status >= 400: continue
                final_host = (urlparse(final_url).hostname or "").lower().removeprefix("www.")
                if base_host and final_host and final_host != base_host: continue
                soup = BeautifulSoup(html, "html.parser")
                for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
                    try:
                        raw = json.loads(script.string or script.get_text() or "{}")
                        for obj in raw if isinstance(raw, list) else [raw]:
                            if not isinstance(obj, dict): continue
                            for kind, value in (("email", obj.get("email")), ("phone", obj.get("telephone"))):
                                cleaned = _lf.clean_email(value) if kind == "email" else _lf.clean_phone(value)
                                if cleaned:
                                    key = (kind, cleaned, final_url)
                                    if key not in seen: seen.add(key); found.append(key)
                    except Exception: pass
                for email in _lf.extract_emails(html):
                    key = ("email", email, final_url)
                    if key not in seen: seen.add(key); found.append(key)
                for anchor in soup.find_all("a", href=True):
                    href = str(anchor.get("href") or "")
                    low = href.lower()
                    if low.startswith("tel:"):
                        phone = _lf.clean_phone(href[4:].split("?")[0])
                        if phone:
                            key = ("phone", phone, final_url)
                            if key not in seen: seen.add(key); found.append(key)
                    elif low.startswith("mailto:"):
                        email = _lf.clean_email(href[7:].split("?")[0])
                        if email:
                            key = ("email", email, final_url)
                            if key not in seen: seen.add(key); found.append(key)
                    elif any(word in (anchor.get_text(" ", strip=True) + " " + href).lower() for word in ["contact", "about", "team", "agent", "staff"]):
                        absolute = urljoin(final_url, href)
                        if (urlparse(absolute).hostname or "").lower().removeprefix("www.") == base_host and absolute not in scanned and absolute not in queue:
                            queue.append(absolute)
                for phone in _lf.extract_phones(html):
                    key = ("phone", phone, final_url)
                    if key not in seen: seen.add(key); found.append(key)
                if url == website:
                    try:
                        r = await client.get(urljoin(website + "/", "sitemap.xml"), headers={"User-Agent": _lf.UA})
                        if r.status_code < 400:
                            for loc in re.findall(r"<loc>(.*?)</loc>", r.text, re.I):
                                if any(k in loc.lower() for k in ["contact", "about", "team", "agent", "staff"]): queue.append(loc.strip())
                    except Exception: pass
            except Exception:
                continue
        return found
    _lf.find_contacts = _broader_find_contacts

    async def _enrich_contacts(client, rows):
        wanted = {}
        for row in rows:
            m = re.match(r"osm:(node|way|relation):(.+)$", str(row.get("source_id") or ""))
            if m: wanted[{"node":"N","way":"W","relation":"R"}[m.group(1)] + m.group(2)] = row
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
            except Exception as exc: print(f"Lead Flow OSM contact enrichment skipped: {exc}", flush=True)
        return rows

    _original_discover = _lf.discover
    async def _discover_with_contacts(city, industry, country, job):
        rows = await discover_exhaustive(_lf, city, industry, country, job, _original_discover)
        if rows:
            async with httpx.AsyncClient(timeout=_lf.TIMEOUT) as client: rows = await _enrich_contacts(client, rows)
        return rows
    _lf.discover = _discover_with_contacts

    from backend.fastapi.job_store import PersistentJobs
    _lf.JOBS = PersistentJobs()
    print(f"Lead Flow durable job store active: {getattr(_lf.JOBS, 'persistent', False)}", flush=True)
except Exception as exc:
    print(f"Lead Flow runtime bootstrap unavailable: {exc}", flush=True)
