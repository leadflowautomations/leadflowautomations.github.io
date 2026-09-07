import asyncio
import json
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import urljoin, urlparse

import sitecustomize  # noqa: F401
import httpx
from bs4 import BeautifulSoup
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "leadflow-fastapi-v2.3.0-progressive-research"
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "12"))
# 0 means no application-level cap. Provider/network limits still apply naturally.
MAX_DISCOVERY_RESULTS = int(os.getenv("MAX_DISCOVERY_RESULTS", "0"))
# 0 means enrich every discovered candidate, in batches.
MAX_WEBSITE_ENRICH = int(os.getenv("MAX_WEBSITE_ENRICH", "0"))
DISCOVERY_RADIUS_METERS = int(os.getenv("DISCOVERY_RADIUS_METERS", "30000"))
RESEARCH_CONCURRENCY = max(1, int(os.getenv("RESEARCH_CONCURRENCY", "8")))
USER_AGENT = "LeadFlowResearch/2.3 (+https://leadflowautomations.github.io/)"

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
        "osm": [("office", "estate_agent"), ("office", "property_management"), ("shop", "estate_agent")],
        "queries": ["real estate", "realty", "realtor", "properties", "property management", "commercial real estate", "residential real estate"],
    },
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
    parsed = urlparse(value)
    if not parsed.netloc:
        return None
    host = parsed.netloc.lower().split(":", 1)[0]
    blocked = {"google.com", "www.google.com", "bing.com", "www.bing.com", "duckduckgo.com", "www.duckduckgo.com", "jina.ai", "r.jina.ai"}
    if host in blocked or host.endswith(".google.com") or host.endswith(".bing.com"):
        return None
    return value.rstrip("/")


def clean_email(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower().replace("mailto:", "").split("?", 1)[0]
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value):
        return None
    local, domain = value.split("@", 1)
    blocked_domains = {"duckduckgo.com", "google.com", "bing.com", "example.com", "sentry.io", "schema.org", "wixpress.com", "wordpress.com", "cloudflare.com"}
    blocked_locals = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster"}
    if domain in blocked_domains or domain.endswith(".google.com") or domain.endswith(".bing.com") or local in blocked_locals:
        return None
    return value


def clean_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15 or len(set(digits)) == 1:
        return None
    return value.strip()


def name_tokens(name: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", name.lower()) if len(x) > 2}


def business_name_matches(business_name: str, page_text: str) -> bool:
    tokens = name_tokens(business_name)
    normalized = re.sub(r"[^a-z0-9]+", " ", page_text.lower())
    if not tokens:
        return False
    hits = sum(token in normalized for token in tokens)
    return hits >= max(1, min(2, len(tokens)))


def industry_config(industry: str) -> dict[str, Any]:
    normalized = industry.lower().strip()
    aliases = {
        "dental": "dentist", "law firm": "law", "beauty": "salon", "hair salon": "salon",
        "auto": "auto repair", "automotive": "auto repair", "realty": "real estate",
        "real estate agency": "real estate", "realtor": "real estate", "property": "real estate",
    }
    return INDUSTRIES.get(aliases.get(normalized, normalized), {"osm": [], "queries": [industry]})


async def geocode(client: httpx.AsyncClient, city: str, country: str) -> tuple[float, float] | None:
    response = await client.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": f"{city}, {country}", "format": "jsonv2", "limit": 1},
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
    last_error: Exception | None = None
    for endpoint in endpoints:
        try:
            response = await client.post(endpoint, data=query, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
            if response.status_code < 400:
                return response.json().get("elements", [])
            last_error = RuntimeError(f"HTTP {response.status_code}")
        except Exception as exc:
            last_error = exc
            print(f"Overpass provider failed: {endpoint}: {exc}")
    if last_error:
        print(f"All Overpass providers failed: {last_error}")
    return []


def escape_overpass_regex(value: str) -> str:
    return re.escape(value).replace('\\\\', '\\\\')


def build_overpass_query(lat: float, lon: float, tags: list[tuple[str, str]], keywords: list[str] | None = None, radius: int = DISCOVERY_RADIUS_METERS) -> str:
    clauses: list[str] = []
    safe_radius = max(5000, min(50000, radius))
    for key, value in tags:
        clauses.extend([
            f'node["{key}"="{value}"](around:{safe_radius},{lat},{lon});',
            f'way["{key}"="{value}"](around:{safe_radius},{lat},{lon});',
            f'relation["{key}"="{value}"](around:{safe_radius},{lat},{lon});',
        ])
    if keywords:
        pattern = "|".join(escape_overpass_regex(word) for word in keywords if word.strip())
        if pattern:
            clauses.append(f'nwr["name"~"{pattern}",i](around:{safe_radius},{lat},{lon});')
    return "[out:json][timeout:55];(" + "".join(clauses) + ");out center tags;"


def element_to_business(element: dict[str, Any], industry: str) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or "").strip()
    if not name:
        return None
    center = element.get("center") or {}
    address = ", ".join(x for x in [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:city"), tags.get("addr:state"), tags.get("addr:postcode")] if x)
    socials = {k: v for k, v in {
        "facebook": tags.get("contact:facebook"), "instagram": tags.get("contact:instagram"),
        "linkedin": tags.get("contact:linkedin"), "twitter": tags.get("contact:twitter"), "youtube": tags.get("contact:youtube"),
    }.items() if v}
    return {
        "source_id": f"osm:{element.get('type')}:{element.get('id')}",
        "name": name,
        "address": address or None,
        "lat": element.get("lat") or center.get("lat"),
        "lon": element.get("lon") or center.get("lon"),
        "phone": clean_phone(tags.get("contact:phone") or tags.get("phone")),
        "email": clean_email(tags.get("contact:email") or tags.get("email")),
        "website": clean_url(tags.get("contact:website") or tags.get("website") or tags.get("url")),
        "social_links": socials,
        "industry": industry,
        "source": "OpenStreetMap",
        "contact_sources": ["OpenStreetMap"] if any([tags.get("contact:phone"), tags.get("phone"), tags.get("contact:email"), tags.get("email")]) else [],
    }


def dedupe_businesses(businesses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in businesses:
        name_key = re.sub(r"[^a-z0-9]+", " ", (item.get("name") or "").lower()).strip()
        address_key = re.sub(r"[^a-z0-9]+", " ", (item.get("address") or "").lower()).strip()
        if not name_key:
            continue
        key = f"{name_key}|{address_key[:100]}" if address_key else name_key
        if key not in deduped:
            deduped[key] = item
            continue
        existing = deduped[key]
        for field in ("phone", "email", "website", "address", "lat", "lon"):
            if not existing.get(field) and item.get(field):
                existing[field] = item[field]
        existing["social_links"] = {**existing.get("social_links", {}), **item.get("social_links", {})}
        existing["contact_sources"] = sorted(set(existing.get("contact_sources", []) + item.get("contact_sources", [])))
    return list(deduped.values())


async def discover(city: str, industry: str, country: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        center = await geocode(client, city, country)
        if not center:
            return []
        config = industry_config(industry)
        raw: list[dict[str, Any]] = []
        # Query structured OSM tags independently. This avoids one oversized query
        # failing and makes the discovery source resilient across provider limits.
        tag_queries = [build_overpass_query(center[0], center[1], [tag]) for tag in config["osm"]]
        structured = await asyncio.gather(*(overpass_query(client, q) for q in tag_queries)) if tag_queries else []
        for elements in structured:
            raw.extend(elements)

        # Name-based fallback is deliberately additive: it catches legitimate
        # businesses whose OSM category is missing/mapped differently. Verification
        # later decides whether the candidate is sufficiently evidenced.
        keyword_queries = [build_overpass_query(center[0], center[1], [], [keyword]) for keyword in config["queries"]]
        keyword_results = await asyncio.gather(*(overpass_query(client, q) for q in keyword_queries)) if keyword_queries else []
        for elements in keyword_results:
            raw.extend(elements)

        businesses = [x for x in (element_to_business(e, industry) for e in raw) if x]
        results = dedupe_businesses(businesses)
        if MAX_DISCOVERY_RESULTS > 0:
            results = results[:MAX_DISCOVERY_RESULTS]
        return results


async def fetch_page(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = await client.get(url, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        return {"ok": response.status_code < 400, "status": response.status_code, "url": str(response.url), "html": response.text[:2_500_000], "seconds": round(time.perf_counter() - started, 2)}
    except Exception as exc:
        return {"ok": False, "status": None, "url": url, "html": "", "seconds": round(time.perf_counter() - started, 2), "error": str(exc)}


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


def extract_phones(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    values: set[str] = set()
    for link in soup.select('a[href^="tel:"]'):
        phone = clean_phone(link.get("href", ""))
        if phone:
            values.add(phone)
    text = soup.get_text(" ", strip=True)
    for raw in re.findall(r"(?:\+?\d[\d\s().-]{8,}\d)", text):
        phone = clean_phone(raw)
        if phone:
            values.add(phone)
    return list(values)


def extract_jsonld_contacts(html: str) -> tuple[list[str], list[str]]:
    emails: set[str] = set()
    phones: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if isinstance(item.get("email"), str):
                    value = clean_email(item["email"])
                    if value:
                        emails.add(value)
                if isinstance(item.get("telephone"), str):
                    value = clean_phone(item["telephone"])
                    if value:
                        phones.add(value)
                for value in item.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(item, list):
                stack.extend(item)
    return list(emails), list(phones)


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
    emails = extract_emails(html)
    phones = extract_phones(html)
    jsonld_emails, jsonld_phones = extract_jsonld_contacts(html)
    emails = list(dict.fromkeys(jsonld_emails + emails))
    phones = list(dict.fromkeys(jsonld_phones + phones))
    booking = ["calendly.com", "acuityscheduling.com", "squareup.com/appointments", "setmore.com", "simplybook.me", "booksy.com", "mindbodyonline.com", "book appointment", "schedule appointment", "book a consultation"]
    chat = ["intercom", "drift.com", "tawk.to", "crisp.chat", "tidio", "zendesk", "livechat", "hubspot"]
    analytics = ["googletagmanager.com", "google-analytics.com", "gtag(", "clarity.ms", "hotjar", "connect.facebook.net"]
    social = ["facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com", "x.com", "twitter.com"]
    qualification = ["budget", "timeframe", "timeline", "project type", "service needed", "property type", "number of", "how can we help", "what are you looking for", "preferred date"]
    review_terms = ["reviews", "testimonials", "client stories", "google reviews", "yelp.com"]
    seo_ok = bool(title.strip()) and bool(description.strip()) and len(title.strip()) >= 10
    return {
        "website_exists": True, "website_working": page.get("ok", False), "https": urlparse(url).scheme.lower() == "https",
        "lead_form": bool(forms) and any(k in form_text + visible_lower for k in ["contact", "quote", "estimate", "inquiry", "request", "lead", "get started"]),
        "booking": any(x in lower for x in booking), "chatbot": any(x in lower or x in scripts for x in chat),
        "analytics": any(x in scripts or x in lower for x in analytics), "qualification": any(x in visible_lower or x in form_text for x in qualification),
        "seo": seo_ok, "social": any(x in lower for x in social), "reviews": any(x in visible_lower or x in lower for x in review_terms),
        "slow": page.get("seconds", 0) > 4, "broken": not page.get("ok", False), "status_code": page.get("status"),
        "response_time": page.get("seconds"), "final_url": page.get("url"), "business_name_found_on_page": business_name_matches(business_name, visible),
        "title": title, "description": description[:300], "headings": headings[:1000], "emails_found": emails[:10], "phones_found": phones[:10],
    }


async def find_contact(client: httpx.AsyncClient, website: str, business_name: str, homepage: str) -> tuple[str | None, str | None, str | None, str | None]:
    candidates = []
    if business_name_matches(business_name, homepage):
        candidates.append((homepage, extract_emails(homepage), extract_phones(homepage)))
    for path in ("/contact", "/contact-us", "/contactus", "/about", "/about-us", "/get-in-touch"):
        try:
            target = urljoin(website + "/", path.lstrip("/"))
            response = await client.get(target, follow_redirects=True, headers={"User-Agent": USER_AGENT})
            if response.status_code >= 400:
                continue
            text = response.text[:1_500_000]
            visible = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
            if not business_name_matches(business_name, visible):
                continue
            emails = extract_emails(text); phones = extract_phones(text)
            json_emails, json_phones = extract_jsonld_contacts(text)
            emails = list(dict.fromkeys(json_emails + emails)); phones = list(dict.fromkeys(json_phones + phones))
            candidates.append((target, emails, phones))
        except Exception:
            continue
    email = next((emails[0] for _, emails, _ in candidates if emails), None)
    phone = next((phones[0] for _, _, phones in candidates if phones), None)
    email_source = next((source for source, emails, _ in candidates if emails), None)
    phone_source = next((source for source, _, phones in candidates if phones), None)
    return email, email_source, phone, phone_source


def score(business: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    weights = {"website": 18, "contact": 10, "booking": 16, "lead_form": 14, "qualification": 12, "chatbot": 10, "analytics": 8, "seo": 7, "social": 3, "reviews": 2}
    gaps: list[str] = []; reasons: list[str] = []; gap_score = 0
    if not signals.get("website_exists") or not signals.get("website_working"):
        gap_score += weights["website"]; gaps.append("Website"); reasons.append("No healthy website was confirmed.")
    contact_missing = int(not business.get("phone")) + int(not business.get("email"))
    if contact_missing:
        gap_score += weights["contact"] if contact_missing == 2 else weights["contact"] // 2; gaps.append("Direct contact"); reasons.append("Public contact coverage is incomplete.")
    if not signals.get("booking"): gap_score += weights["booking"]; gaps.append("Booking")
    if not signals.get("lead_form"): gap_score += weights["lead_form"]; gaps.append("Lead capture")
    if not signals.get("qualification"): gap_score += weights["qualification"]; gaps.append("Qualification")
    if not signals.get("chatbot"): gap_score += weights["chatbot"]; gaps.append("AI/live chat")
    if not signals.get("analytics"): gap_score += weights["analytics"]; gaps.append("Analytics")
    if signals.get("website_exists") and signals.get("website_working") and not signals.get("seo"): gap_score += weights["seo"]; gaps.append("SEO foundation")
    if not signals.get("social"): gap_score += weights["social"]; gaps.append("Social proof/presence")
    if not signals.get("reviews"): gap_score += weights["reviews"]; gaps.append("Reviews/testimonials")
    value = min(100, gap_score)
    tier = "Very High" if value >= 75 else "High" if value >= 55 else "Moderate" if value >= 35 else "Low"
    prospect_type = "website_build" if not signals.get("website_exists") else "website_repair" if not signals.get("website_working") else "automation_upgrade"
    return {"score": value, "tier": tier, "prospect_type": prospect_type, "gaps": gaps, "reasons": reasons, "scoring_version": APP_VERSION, "score_definition": "0-100 evidence-based automation opportunity; higher means more confirmed gaps."}


def empty_signals(item: dict[str, Any]) -> dict[str, Any]:
    return {"website_exists": False, "website_working": False, "https": False, "lead_form": False, "booking": False, "chatbot": False, "analytics": False, "qualification": False, "seo": False, "social": bool(item.get("social_links")), "reviews": False, "slow": False, "broken": False, "status_code": None, "response_time": None, "final_url": None, "business_name_found_on_page": False, "emails_found": [], "phones_found": []}


async def research_one(client: httpx.AsyncClient, item: dict[str, Any], semaphore: asyncio.Semaphore) -> dict[str, Any]:
    async with semaphore:
        website = item.get("website")
        if not website:
            signals = empty_signals(item); item["research_status"] = "no_website"
        else:
            page = await fetch_page(client, website)
            signals = inspect_site(website, page, item.get("name") or "")
            item["research_status"] = "inspected" if signals.get("business_name_found_on_page") else "website_unconfirmed"
            if page.get("html") and signals.get("business_name_found_on_page"):
                email, email_source, phone, phone_source = await find_contact(client, website, item.get("name") or "", page.get("html", ""))
                if not item.get("email") and email: item["email"], item["email_source"] = email, email_source
                if not item.get("phone") and phone: item["phone"], item["phone_source"] = phone, phone_source
        item["contactability"] = {"phone": bool(item.get("phone")), "email": bool(item.get("email")), "website": bool(item.get("website")), "verified_from_business_site": bool(item.get("email_source") or item.get("phone_source"))}
        item["contact_sources"] = sorted(set(item.get("contact_sources", []) + [x for x in [item.get("email_source"), item.get("phone_source")] if x]))
        item["signals"] = signals; item.update(score(item, signals))
        return item


async def process_research_job(job_id: str, city: str, industry: str, country: str) -> None:
    job = JOBS.get(job_id)
    if not job: return
    started = time.perf_counter()
    try:
        job.update({"status": "discovering", "stage": "discover", "message": f"Locating {city}, {country}…", "updated_at": time.time()})
        businesses = await discover(city, industry, country)
        job.update({"candidate_count": len(businesses), "discovered": len(businesses), "status": "researching", "stage": "research", "message": f"Discovered {len(businesses)} candidates. Researching in parallel batches…", "updated_at": time.time()})
        semaphore = asyncio.Semaphore(RESEARCH_CONCURRENCY)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            results: list[dict[str, Any]] = []
            limit = len(businesses) if MAX_WEBSITE_ENRICH <= 0 else min(len(businesses), MAX_WEBSITE_ENRICH)
            for start in range(0, limit, RESEARCH_CONCURRENCY):
                batch = businesses[start:start + RESEARCH_CONCURRENCY]
                batch_results = await asyncio.gather(*(research_one(client, item, semaphore) for item in batch), return_exceptions=True)
                for result in batch_results:
                    if isinstance(result, Exception):
                        job["errors"] += 1
                        continue
                    results.append(result)
                results.sort(key=lambda x: (x.get("score", 0), int(x.get("contactability", {}).get("phone", False)) + int(x.get("contactability", {}).get("email", False))), reverse=True)
                for rank, item in enumerate(results, 1): item["rank"] = rank
                job.update({"processed": len(results), "completed": len(results), "results": results, "message": f"Processed {len(results)} of {limit} candidates…", "updated_at": time.time()})
        job.update({"status": "complete", "stage": "complete", "message": f"Research complete — {len(results)} candidates scored and ranked.", "duration_seconds": round(time.perf_counter() - started, 2), "updated_at": time.time()})
    except Exception as exc:
        job.update({"status": "failed", "stage": "error", "message": "Research job failed.", "error": str(exc)[:500], "duration_seconds": round(time.perf_counter() - started, 2), "updated_at": time.time()})


JOBS: dict[str, dict[str, Any]] = {}


@app.get("/")
async def root():
    return {"service": "Lead Flow Intelligence API", "version": APP_VERSION, "status": "online", "discovery": "OpenStreetMap + Overpass + Nominatim geocoding", "google_required": False, "scoring": "evidence-based opportunity gaps", "research": "progressive background jobs", "discovery_limit": MAX_DISCOVERY_RESULTS or None}


@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION, "google_api_required": False, "discovery": "osm+overpass", "research": "progressive background jobs", "active_jobs": sum(1 for j in JOBS.values() if j.get("status") not in {"complete", "failed"})}


@app.post("/research-jobs")
async def create_research_job(background_tasks: BackgroundTasks, city: str = Query(..., min_length=1), industry: str = Query(..., min_length=1), country: str = Query(..., min_length=1)):
    city, industry, country = city.strip(), industry.strip(), country.strip()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"job_id": job_id, "city": city, "country": country, "industry": industry, "status": "queued", "stage": "queued", "message": "Research job queued.", "candidate_count": 0, "discovered": 0, "processed": 0, "completed": 0, "errors": 0, "results": [], "created_at": time.time(), "updated_at": time.time()}
    background_tasks.add_task(process_research_job, job_id, city, industry, country)
    return {"ok": True, "job_id": job_id, "status": "queued", "poll_url": f"/research-jobs/{job_id}"}


@app.get("/research-jobs/{job_id}")
async def get_research_job(job_id: str):
    job = JOBS.get(job_id)
    if not job: raise HTTPException(status_code=404, detail="Research job not found.")
    return {k: v for k, v in job.items() if k != "results"} | {"result_count": len(job.get("results", [])), "results": job.get("results", [])}


@app.get("/scan")
async def scan(city: str = Query(..., min_length=1), industry: str = Query(..., min_length=1), country: str = Query(..., min_length=1)):
    # Backward-compatible synchronous endpoint. New clients should use /research-jobs
    # so large searches can continue after the HTTP request returns.
    started = time.perf_counter()
    results = await discover(city.strip(), industry.strip(), country.strip())
    semaphore = asyncio.Semaphore(RESEARCH_CONCURRENCY)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        limit = len(results) if MAX_WEBSITE_ENRICH <= 0 else min(len(results), MAX_WEBSITE_ENRICH)
        processed = await asyncio.gather(*(research_one(client, item, semaphore) for item in results[:limit]))
    processed.sort(key=lambda x: (x.get("score", 0), int(x.get("contactability", {}).get("phone", False)) + int(x.get("contactability", {}).get("email", False))), reverse=True)
    for rank, item in enumerate(processed, 1): item["rank"] = rank
    return {"city": city.strip(), "country": country.strip(), "industry": industry.strip(), "count": len(processed), "discovered_count": len(results), "duration_seconds": round(time.perf_counter() - started, 2), "results": processed}
