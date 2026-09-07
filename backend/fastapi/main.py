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

APP_VERSION = "leadflow-fastapi-v2.1.0-intelligence"
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "12"))
MAX_DISCOVERY_RESULTS = int(os.getenv("MAX_DISCOVERY_RESULTS", "100"))
USER_AGENT = "LeadFlowResearch/2.1 (+https://leadflowautomations.github.io/; contact: leadflowautomations-dav@outlook.com)"

app = FastAPI(title="Lead Flow Intelligence API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://leadflowautomations.github.io",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

INDUSTRIES = {
    "real estate": {
        "osm": [("office", "estate_agent"), ("office", "property_management")],
        "queries": ["real estate", "realty", "realtor", "property management"],
    },
    "law": {"osm": [("office", "lawyer")], "queries": ["law firm", "lawyer", "attorney"]},
    "dentist": {"osm": [("amenity", "dentist")], "queries": ["dentist", "dental clinic"]},
    "restaurant": {
        "osm": [("amenity", "restaurant"), ("amenity", "cafe")],
        "queries": ["restaurant", "cafe"],
    },
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
    parsed = urlparse(value)
    return value.rstrip("/") if parsed.netloc else None


def clean_email(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower().replace("mailto:", "").split("?", 1)[0]
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value):
        return None
    domain = value.split("@", 1)[1]
    if domain in {
        "duckduckgo.com", "google.com", "bing.com", "example.com", "sentry.io",
        "schema.org", "wixpress.com", "wordpress.com", "cloudflare.com",
    }:
        return None
    return value


def clean_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15:
        return None
    if len(set(digits)) == 1 or (len(digits) == 10 and digits.startswith("1")):
        return None
    if len(digits) == 11 and digits.startswith("1") and digits[1] == "0":
        return None
    return value.strip()


def name_tokens(name: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", name.lower()) if len(x) > 2}


def business_name_matches(business_name: str, page_text: str) -> bool:
    tokens = name_tokens(business_name)
    normalized = re.sub(r"[^a-z0-9]+", " ", page_text.lower())
    return bool(tokens) and sum(token in normalized for token in tokens) >= max(1, min(2, len(tokens)))


def industry_config(industry: str) -> dict[str, Any]:
    normalized = industry.lower().strip()
    aliases = {
        "dental": "dentist",
        "law firm": "law",
        "beauty": "salon",
        "hair salon": "salon",
        "auto": "auto repair",
        "automotive": "auto repair",
    }
    return INDUSTRIES.get(aliases.get(normalized, normalized), {"osm": [], "queries": [industry]})


async def geocode(client: httpx.AsyncClient, city: str, country: str) -> tuple[float, float] | None:
    response = await client.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": f"{city}, {country}", "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT, "Referer": "https://leadflowautomations.github.io/"},
    )
    response.raise_for_status()
    rows = response.json()
    return (float(rows[0]["lat"]), float(rows[0]["lon"])) if rows else None


async def overpass_query(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]
    for endpoint in endpoints:
        try:
            response = await client.post(endpoint, data=query, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
            if response.status_code < 400:
                return response.json().get("elements", [])
        except Exception as exc:
            print(f"Overpass provider failed: {endpoint}: {exc}")
    return []


def build_overpass_query(lat: float, lon: float, tags: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for key, value in tags:
        parts.extend([
            f'node["{key}"="{value}"](around:20000,{lat},{lon});',
            f'way["{key}"="{value}"](around:20000,{lat},{lon});',
            f'relation["{key}"="{value}"](around:20000,{lat},{lon});',
        ])
    return "[out:json][timeout:18];(" + "".join(parts) + ");out center tags;"


def element_to_business(element: dict[str, Any], industry: str) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or "").strip()
    if not name:
        return None
    center = element.get("center") or {}
    address = ", ".join(
        x for x in [
            tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city"),
            tags.get("addr:state"), tags.get("addr:postcode")
        ] if x
    )
    return {
        "source_id": f"osm:{element.get('type')}:{element.get('id')}",
        "name": name,
        "address": address or None,
        "lat": element.get("lat") or center.get("lat"),
        "lon": element.get("lon") or center.get("lon"),
        "phone": clean_phone(tags.get("contact:phone") or tags.get("phone")),
        "email": clean_email(tags.get("contact:email") or tags.get("email")),
        "website": clean_url(tags.get("contact:website") or tags.get("website") or tags.get("url")),
        "industry": industry,
        "source": "OpenStreetMap",
    }


async def nominatim_discover(client: httpx.AsyncClient, city: str, country: str, industry: str) -> list[dict[str, Any]]:
    config = industry_config(industry)
    term = config["queries"][0] if config["queries"] else industry
    try:
        response = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": f"{term}, {city}, {country}",
                "format": "json",
                "limit": 50,
                "addressdetails": 1,
                "namedetails": 1,
            },
            headers={"User-Agent": USER_AGENT, "Referer": "https://leadflowautomations.github.io/"},
        )
        if response.status_code >= 400:
            return []
        results = []
        for row in response.json():
            display = row.get("display_name", "")
            name = (row.get("name") or row.get("namedetails", {}).get("name") or display.split(",", 1)[0]).strip()
            if not name:
                continue
            results.append({
                "source_id": f"nominatim:{row.get('osm_type')}:{row.get('osm_id')}",
                "name": name,
                "address": display,
                "lat": float(row["lat"]) if row.get("lat") else None,
                "lon": float(row["lon"]) if row.get("lon") else None,
                "phone": None,
                "email": None,
                "website": None,
                "industry": industry,
                "source": "Nominatim/OpenStreetMap",
            })
        return results
    except Exception as exc:
        print(f"Nominatim discovery failed for {term}: {exc}")
        return []


async def discover(city: str, industry: str, country: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        center = await geocode(client, city, country)
        raw: list[dict[str, Any]] = []
        config = industry_config(industry)
        if center and config["osm"]:
            raw = [x for x in await overpass_query(client, build_overpass_query(center[0], center[1], config["osm"])) if x.get("tags")]
        businesses = [x for x in (element_to_business(e, industry) for e in raw) if x]
        if len(businesses) < min(25, MAX_DISCOVERY_RESULTS):
            businesses.extend(await nominatim_discover(client, city, country, industry))
        deduped: dict[str, dict[str, Any]] = {}
        for item in businesses:
            name_key = re.sub(r"[^a-z0-9]+", " ", (item.get("name") or "").lower()).strip()
            address_key = re.sub(r"[^a-z0-9]+", " ", (item.get("address") or "").lower()).strip()
            key = f"{name_key}|{address_key[:80]}" if address_key else name_key
            if not name_key:
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
        response = await client.get(
            url,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        return {
            "ok": response.status_code < 400,
            "status": response.status_code,
            "url": str(response.url),
            "html": response.text[:2_500_000],
            "seconds": round(time.perf_counter() - started, 2),
        }
    except Exception as exc:
        return {
            "ok": False, "status": None, "url": url, "html": "",
            "seconds": round(time.perf_counter() - started, 2), "error": str(exc),
        }


def inspect_site(url: str, page: dict[str, Any], business_name: str) -> dict[str, Any]:
    html = page.get("html", "")
    lower = html.lower()
    soup = BeautifulSoup(html, "html.parser")
    visible = soup.get_text(" ", strip=True)
    visible_lower = visible.lower()
    scripts = " ".join(str(x) for x in soup.find_all("script")).lower()
    forms = soup.find_all("form")
    form_text = " ".join(str(x) for x in forms).lower()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    description = description_tag.get("content", "") if description_tag else ""
    headings = " ".join(x.get_text(" ", strip=True) for x in soup.find_all(["h1", "h2", "h3"]))
    booking = [
        "calendly.com", "acuityscheduling.com", "squareup.com/appointments", "setmore.com",
        "simplybook.me", "booksy.com", "mindbodyonline.com", "book appointment",
        "schedule appointment", "book a consultation",
    ]
    chat = ["intercom", "drift.com", "tawk.to", "crisp.chat", "tidio", "zendesk", "livechat", "hubspot"]
    analytics = ["googletagmanager.com", "google-analytics.com", "gtag(", "clarity.ms", "hotjar", "connect.facebook.net"]
    social = ["facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com", "x.com", "twitter.com"]
    qualification = [
        "budget", "timeframe", "timeline", "project type", "service needed", "property type",
        "number of", "how can we help", "what are you looking for", "preferred date",
    ]
    review_terms = ["reviews", "testimonials", "client stories", "google reviews", "yelp.com"]
    seo_ok = bool(title.strip()) and bool(description.strip()) and len(title.strip()) >= 10
    return {
        "website_exists": True,
        "website_working": page.get("ok", False),
        "https": urlparse(url).scheme.lower() == "https",
        "lead_form": bool(forms) and any(k in form_text + visible_lower for k in ["contact", "quote", "estimate", "inquiry", "request", "lead", "get started"]),
        "booking": any(x in lower for x in booking),
        "chatbot": any(x in lower or x in scripts for x in chat),
        "analytics": any(x in scripts or x in lower for x in analytics),
        "qualification": any(x in visible_lower or x in form_text for x in qualification),
        "seo": seo_ok,
        "social": any(x in lower for x in social),
        "reviews": any(x in visible_lower or x in lower for x in review_terms),
        "slow": page.get("seconds", 0) > 4,
        "broken": not page.get("ok", False),
        "status_code": page.get("status"),
        "response_time": page.get("seconds"),
        "final_url": page.get("url"),
        "business_name_found_on_page": business_name_matches(business_name, visible),
        "title": title,
        "description": description[:300],
        "headings": headings[:1000],
    }


def extract_emails(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    values: set[str] = set()
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
    weights = {
        "website": 18, "contact": 10, "booking": 16, "lead_form": 14,
        "qualification": 12, "chatbot": 10, "analytics": 8, "seo": 7,
        "social": 3, "reviews": 2,
    }
    gaps: list[str] = []
    reasons: list[str] = []
    gap_score = 0

    if not signals.get("website_exists") or not signals.get("website_working"):
        gap_score += weights["website"]
        gaps.append("Website")
        reasons.append("No healthy website was confirmed.")

    contact_missing = int(not business.get("phone")) + int(not business.get("email"))
    if contact_missing:
        contact_points = weights["contact"] if contact_missing == 2 else weights["contact"] // 2
        gap_score += contact_points
        gaps.append("Direct contact")
        reasons.append("Public contact coverage is incomplete.")

    if not signals.get("booking"):
        gap_score += weights["booking"]
        gaps.append("Booking")
    if not signals.get("lead_form"):
        gap_score += weights["lead_form"]
        gaps.append("Lead capture")
    if not signals.get("qualification"):
        gap_score += weights["qualification"]
        gaps.append("Qualification")
    if not signals.get("chatbot"):
        gap_score += weights["chatbot"]
        gaps.append("AI/live chat")
    if not signals.get("analytics"):
        gap_score += weights["analytics"]
        gaps.append("Analytics")
    if signals.get("website_exists") and signals.get("website_working") and not signals.get("seo"):
        gap_score += weights["seo"]
        gaps.append("SEO foundation")
    if not signals.get("social"):
        gap_score += weights["social"]
        gaps.append("Social proof/presence")
    if not signals.get("reviews"):
        gap_score += weights["reviews"]
        gaps.append("Reviews/testimonials")

    value = min(100, gap_score)
    tier = "Very High" if value >= 75 else "High" if value >= 55 else "Moderate" if value >= 35 else "Low"
    prospect_type = "website_build" if not signals.get("website_exists") else "website_repair" if not signals.get("website_working") else "automation_upgrade"
    return {
        "score": value,
        "tier": tier,
        "prospect_type": prospect_type,
        "gaps": gaps,
        "reasons": reasons,
        "scoring_version": APP_VERSION,
        "score_definition": "0-100 evidence-based automation opportunity; higher means more confirmed gaps.",
    }


async def run_scan(city: str, industry: str, country: str) -> list[dict[str, Any]]:
    businesses = await discover(city, industry, country)
    semaphore = asyncio.Semaphore(6)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        async def research(item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                website = item.get("website")
                if not website:
                    signals = {
                        "website_exists": False, "website_working": False, "https": False,
                        "lead_form": False, "booking": False, "chatbot": False, "analytics": False,
                        "qualification": False, "seo": False, "social": False, "reviews": False,
                        "slow": False, "broken": False, "status_code": None, "response_time": None,
                        "final_url": None, "business_name_found_on_page": False,
                    }
                else:
                    page = await fetch_page(client, website)
                    signals = inspect_site(website, page, item.get("name") or "")
                    if not item.get("email") and page.get("html"):
                        email, source = await find_email(client, website, item.get("name") or "", page.get("html", ""))
                        if email:
                            item["email"], item["email_source"] = email, source
                item["signals"] = signals
                item.update(score(item, signals))
                return item
        results = await asyncio.gather(*(research(x) for x in businesses))

    results.sort(key=lambda x: (x.get("score", 0), len(x.get("gaps", []))), reverse=True)
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    return results


@app.get("/")
async def root():
    return {
        "service": "Lead Flow Intelligence API",
        "version": APP_VERSION,
        "status": "online",
        "discovery": "OpenStreetMap + Nominatim + Overpass",
        "google_required": False,
        "scoring": "evidence-based opportunity gaps",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "google_api_required": False,
        "discovery": "osm+nominatim+overpass",
        "scoring": "evidence-based opportunity gaps",
    }


@app.get("/scan")
async def scan(
    city: str = Query(..., min_length=1),
    industry: str = Query(..., min_length=1),
    country: str = Query(..., min_length=1),
):
    started = time.perf_counter()
    results = await run_scan(city.strip(), industry.strip(), country.strip())
    return {
        "city": city.strip(),
        "country": country.strip(),
        "industry": industry.strip(),
        "count": len(results),
        "duration_seconds": round(time.perf_counter() - started, 2),
        "results": results,
    }
