import asyncio
import os
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "leadflow-fastapi-v2.0.0-no-google"
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "12"))
MAX_DISCOVERY_RESULTS = int(os.getenv("MAX_DISCOVERY_RESULTS", "100"))
USER_AGENT = "LeadFlowResearch/2.0 (business research service)"

app = FastAPI(title="Lead Flow Intelligence API", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["https://leadflowautomations.github.io", "http://localhost:5500", "http://127.0.0.1:5500"], allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

INDUSTRIES = {
    "real estate": {"osm": [("office", "estate_agent")], "queries": ["real estate", "realty", "realtor", "property management"]},
    "law": {"osm": [("office", "lawyer")], "queries": ["law firm", "lawyer", "attorney"]},
    "dentist": {"osm": [("amenity", "dentist")], "queries": ["dentist", "dental clinic"]},
    "restaurant": {"osm": [("amenity", "restaurant"), ("amenity", "cafe")], "queries": ["restaurant", "cafe"]},
    "salon": {"osm": [("shop", "hairdresser")], "queries": ["hair salon", "beauty salon", "barber"]},
    "auto repair": {"osm": [("shop", "car_repair")], "queries": ["auto repair", "car repair", "mechanic"]},
}


def clean_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value.rstrip("/") if urlparse(value).netloc else None


def clean_email(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower().replace("mailto:", "").split("?", 1)[0]
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value):
        return None
    if value.split("@", 1)[1] in {"duckduckgo.com", "google.com", "bing.com", "example.com", "sentry.io", "schema.org", "wixpress.com", "wordpress.com"}:
        return None
    return value


def clean_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15 or len(set(digits)) == 1 or (len(digits) == 10 and digits.startswith("1")):
        return None
    return value.strip()


def name_tokens(name: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", name.lower()) if len(x) > 2}


def business_name_matches(business_name: str, page_text: str) -> bool:
    tokens = name_tokens(business_name)
    normalized = re.sub(r"[^a-z0-9]+", " ", page_text.lower())
    return bool(tokens) and sum(token in normalized for token in tokens) >= max(1, min(2, len(tokens)))


def industry_config(industry: str) -> dict[str, Any]:
    return INDUSTRIES.get(industry.lower().strip(), {"osm": [], "queries": [industry]})


async def geocode(client: httpx.AsyncClient, city: str, country: str) -> tuple[float, float] | None:
    response = await client.get("https://nominatim.openstreetmap.org/search", params={"q": f"{city}, {country}", "format": "json", "limit": 1}, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    rows = response.json()
    return (float(rows[0]["lat"]), float(rows[0]["lon"])) if rows else None


async def overpass_query(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    for endpoint in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]:
        try:
            response = await client.post(endpoint, data=query, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
            if response.status_code < 400:
                return response.json().get("elements", [])
        except Exception as exc:
            print(f"Overpass provider failed: {endpoint}: {exc}")
    return []


def build_overpass_query(lat: float, lon: float, tags: list[tuple[str, str]]) -> str:
    parts = []
    for key, value in tags:
        parts.extend([f'node["{key}"="{value}"](around:20000,{lat},{lon});', f'way["{key}"="{value}"](around:20000,{lat},{lon});', f'relation["{key}"="{value}"](around:20000,{lat},{lon});'])
    return "[out:json][timeout:18];(" + "".join(parts) + ");out center tags;"


def element_to_business(element: dict[str, Any], industry: str) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or "").strip()
    if not name:
        return None
    center = element.get("center") or {}
    address = ", ".join(x for x in [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city"), tags.get("addr:state"), tags.get("addr:postcode")] if x)
    return {
        "source_id": f"osm:{element.get('type')}:{element.get('id')}", "name": name, "address": address or None,
        "lat": element.get("lat") or center.get("lat"), "lon": element.get("lon") or center.get("lon"),
        "phone": clean_phone(tags.get("contact:phone") or tags.get("phone")), "email": clean_email(tags.get("contact:email") or tags.get("email")),
        "website": clean_url(tags.get("contact:website") or tags.get("website") or tags.get("url")), "industry": industry, "source": "OpenStreetMap",
    }


async def nominatim_discover(client: httpx.AsyncClient, city: str, country: str, industry: str) -> list[dict[str, Any]]:
    results = []
    for term in industry_config(industry)["queries"][:4]:
        try:
            response = await client.get("https://nominatim.openstreetmap.org/search", params={"q": f"{term}, {city}, {country}", "format": "json", "limit": 15, "addressdetails": 1}, headers={"User-Agent": USER_AGENT})
            if response.status_code >= 400:
                continue
            for row in response.json():
                display = row.get("display_name", "")
                name = (row.get("name") or row.get("namedetails", {}).get("name") or display.split(",", 1)[0]).strip()
                if name:
                    results.append({"source_id": f"nominatim:{row.get('osm_type')}:{row.get('osm_id')}", "name": name, "address": display, "lat": float(row["lat"]) if row.get("lat") else None, "lon": float(row["lon"]) if row.get("lon") else None, "phone": None, "email": None, "website": None, "industry": industry, "source": "Nominatim/OpenStreetMap"})
        except Exception as exc:
            print(f"Nominatim discovery failed for {term}: {exc}")
    return results


async def discover(city: str, industry: str, country: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        center = await geocode(client, city, country)
        raw = []
        config = industry_config(industry)
        if center and config["osm"]:
            raw = [x for x in await overpass_query(client, build_overpass_query(center[0], center[1], config["osm"])) if x.get("tags")]
        businesses = [x for x in (element_to_business(e, industry) for e in raw) if x]
        businesses.extend(await nominatim_discover(client, city, country, industry))
        deduped: dict[str, dict[str, Any]] = {}
        for item in businesses:
            key = re.sub(r"[^a-z0-9]+", " ", (item.get("name") or "").lower()).strip()
            if not key:
                continue
            if key not in deduped:
                deduped[key] = item
            else:
                for field in ("phone", "email", "website", "address", "lat", "lon"):
                    if not deduped[key].get(field) and item.get(field):
                        deduped[key][field] = item[field]
                deduped[key]["source"] = "OpenStreetMap/Nominatim"
        return list(deduped.values())[:MAX_DISCOVERY_RESULTS]


async def fetch_page(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = await client.get(url, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        return {"ok": response.status_code < 400, "status": response.status_code, "url": str(response.url), "html": response.text[:2_500_000], "seconds": round(time.perf_counter() - started, 2)}
    except Exception as exc:
        return {"ok": False, "status": None, "url": url, "html": "", "seconds": round(time.perf_counter() - started, 2), "error": str(exc)}


def inspect_site(url: str, page: dict[str, Any], business_name: str) -> dict[str, Any]:
    html = page.get("html", "")
    lower = html.lower()
    soup = BeautifulSoup(html, "html.parser")
    visible = soup.get_text(" ", strip=True).lower()
    scripts = " ".join(str(x) for x in soup.find_all("script")).lower()
    forms = soup.find_all("form")
    form_text = " ".join(str(x) for x in forms).lower()
    booking = ["calendly.com", "acuityscheduling.com", "squareup.com/appointments", "setmore.com", "simplybook.me", "booksy.com", "mindbodyonline.com", "book appointment", "schedule appointment", "book a consultation"]
    chat = ["intercom", "drift.com", "tawk.to", "crisp.chat", "tidio", "zendesk", "livechat", "hubspot"]
    analytics = ["googletagmanager.com", "google-analytics.com", "gtag(", "clarity.ms", "hotjar", "connect.facebook.net"]
    return {"website_exists": True, "website_working": page.get("ok", False), "https": urlparse(url).scheme.lower() == "https", "lead_form": bool(forms) and any(k in form_text + visible for k in ["contact", "quote", "estimate", "inquiry", "request", "lead", "get started"]), "booking": any(x in lower for x in booking), "chatbot": any(x in lower or x in scripts for x in chat), "analytics": any(x in scripts or x in lower for x in analytics), "slow": page.get("seconds", 0) > 4, "broken": not page.get("ok", False), "status_code": page.get("status"), "response_time": page.get("seconds"), "final_url": page.get("url"), "business_name_found_on_page": business_name_matches(business_name, visible)}


def extract_emails(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    values = set()
    for link in soup.select('a[href^="mailto:"]'):
        email = clean_email(link.get("href", ""))
        if email:
            values.add(email)
    for raw in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html):
        email = clean_email(raw)
        if email:
            values.add(email)
    return list(values)


async def find_email(client: httpx.AsyncClient, website: str, business_name: str, homepage: str) -> tuple[str | None, str | None]:
    if business_name_matches(business_name, homepage):
        emails = extract_emails(homepage)
        if emails:
            return emails[0], "homepage"
    for path in ("/contact", "/contact-us", "/about", "/about-us"):
        try:
            target = urljoin(website + "/", path.lstrip("/"))
            response = await client.get(target, follow_redirects=True, headers={"User-Agent": USER_AGENT})
            if response.status_code >= 400:
                continue
            text = response.text[:1_500_000]
            if not business_name_matches(business_name, BeautifulSoup(text, "html.parser").get_text(" ", strip=True)):
                continue
            emails = extract_emails(text)
            if emails:
                return emails[0], target
        except Exception:
            pass
    return None, None


def score(business: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    points = 0
    gaps = []
    reasons = []
    if business.get("phone"): points += 10
    else: gaps.append("No verified phone")
    if business.get("email"): points += 10
    else: gaps.append("No verified email")
    if not signals.get("website_exists"):
        points += 30; gaps.append("Website build"); reasons.append("No website found; strong website-build prospect.")
    else:
        if signals.get("website_working"): points += 5
        else: points += 12; gaps.append("Broken website"); reasons.append("Website did not return a healthy response.")
        if signals.get("lead_form"): points += 4
        else: points += 10; gaps.append("Lead capture")
        if signals.get("booking"): points += 3
        else: points += 10; gaps.append("Booking")
        if signals.get("chatbot"): points += 2
        else: points += 8; gaps.append("Chat/AI")
        if signals.get("analytics"): points += 2
        else: points += 5; gaps.append("Analytics")
        if signals.get("https"): points += 5
        else: gaps.append("HTTPS")
        if signals.get("slow"): points += 5; gaps.append("Slow site")
    value = min(100, points)
    tier = "Very High" if value >= 75 else "High" if value >= 55 else "Moderate" if value >= 35 else "Low"
    return {"score": value, "tier": tier, "prospect_type": "website_build" if not signals.get("website_exists") else "automation_upgrade", "gaps": gaps, "reasons": reasons}


async def run_scan(city: str, industry: str, country: str) -> list[dict[str, Any]]:
    businesses = await discover(city, industry, country)
    semaphore = asyncio.Semaphore(6)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        async def research(item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                website = item.get("website")
                if not website:
                    signals = {"website_exists": False, "website_working": False, "https": False, "lead_form": False, "booking": False, "chatbot": False, "analytics": False, "slow": False, "broken": False, "status_code": None, "response_time": None, "final_url": None}
                else:
                    page = await fetch_page(client, website)
                    signals = inspect_site(website, page, item.get("name") or "")
                    if not item.get("email"):
                        email, source = await find_email(client, website, item.get("name") or "", page.get("html", ""))
                        if email:
                            item["email"], item["email_source"] = email, source
                item["signals"] = signals
                item.update(score(item, signals))
                return item
        results = await asyncio.gather(*(research(x) for x in businesses))
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    for rank, item in enumerate(results, 1): item["rank"] = rank
    return results


@app.get("/")
async def root():
    return {"service": "Lead Flow Intelligence API", "version": APP_VERSION, "status": "online", "discovery": "OpenStreetMap + Nominatim + Overpass", "google_required": False}


@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION, "google_api_required": False, "discovery": "osm+nominatim+overpass"}


@app.get("/scan")
async def scan(city: str = Query(..., min_length=1), industry: str = Query(..., min_length=1), country: str = Query(..., min_length=1)):
    results = await run_scan(city.strip(), industry.strip(), country.strip())
    return {"city": city.strip(), "country": country.strip(), "industry": industry.strip(), "count": len(results), "results": results}
