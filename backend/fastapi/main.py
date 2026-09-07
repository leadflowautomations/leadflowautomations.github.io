import asyncio
import os
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


APP_VERSION = "leadflow-fastapi-v1.0.0"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "12"))
MAX_DISCOVERY_RESULTS = int(os.getenv("MAX_DISCOVERY_RESULTS", "100"))

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


def clean_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value.rstrip("/")


def clean_email(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value):
        return None
    domain = value.split("@", 1)[1]
    blocked = {
        "duckduckgo.com", "google.com", "bing.com", "example.com",
        "sentry.io", "schema.org", "wixpress.com", "wordpress.com",
    }
    if domain in blocked:
        return None
    return value


def clean_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15:
        return None
    if len(set(digits)) == 1:
        return None
    # Reject common ten-digit search/system artifacts.
    if len(digits) == 10 and digits.startswith("1"):
        return None
    return value.strip()


def name_tokens(name: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", name.lower()) if len(x) > 2}


def business_name_matches(business_name: str, page_text: str) -> bool:
    tokens = name_tokens(business_name)
    if not tokens:
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", page_text.lower())
    hits = sum(1 for token in tokens if token in normalized)
    return hits >= max(1, min(2, len(tokens)))


INDUSTRY_ALIASES = {
    "real estate": ["real estate", "realty", "realtor", "property", "brokerage", "homes"],
    "law": ["law", "attorney", "legal", "lawyer"],
    "dentist": ["dentist", "dental"],
    "restaurant": ["restaurant", "cafe", "eatery", "bistro"],
    "salon": ["salon", "hair", "beauty", "barber"],
    "auto repair": ["auto repair", "car repair", "automotive", "mechanic"],
}


def discovery_queries(city: str, industry: str, country: str) -> list[str]:
    aliases = INDUSTRY_ALIASES.get(industry.lower().strip(), [industry])
    queries = []
    for alias in aliases[:6]:
        queries.extend([
            f"{alias} in {city}, {country}",
            f"{alias} company in {city}, {country}",
        ])
    return list(dict.fromkeys(queries))


async def places_text_search(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    if not GOOGLE_API_KEY:
        raise HTTPException(503, "GOOGLE_API_KEY is not configured on the backend.")

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
    }
    response = await client.post(url, headers=headers, json={"textQuery": query, "pageSize": 20})
    response.raise_for_status()
    return response.json().get("places", [])


async def place_details(client: httpx.AsyncClient, place_id: str) -> dict[str, Any]:
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "id,displayName,formattedAddress,nationalPhoneNumber,internationalPhoneNumber,websiteUri",
    }
    response = await client.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


async def discover(city: str, industry: str, country: str) -> list[dict[str, Any]]:
    businesses: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for query in discovery_queries(city, industry, country):
            try:
                places = await places_text_search(client, query)
            except Exception as exc:
                print(f"discovery query failed: {query}: {exc}")
                continue
            for place in places:
                pid = place.get("id")
                if not pid:
                    continue
                businesses.setdefault(pid, {
                    "place_id": pid,
                    "name": place.get("displayName", {}).get("text"),
                    "address": place.get("formattedAddress"),
                })
                if len(businesses) >= MAX_DISCOVERY_RESULTS:
                    break
            if len(businesses) >= MAX_DISCOVERY_RESULTS:
                break

        items = list(businesses.values())
        semaphore = asyncio.Semaphore(8)

        async def enrich(item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                try:
                    details = await place_details(client, item["place_id"])
                    item["phone"] = clean_phone(details.get("nationalPhoneNumber") or details.get("internationalPhoneNumber"))
                    item["website"] = clean_url(details.get("websiteUri"))
                except Exception as exc:
                    print(f"details failed for {item.get('name')}: {exc}")
                    item["phone"] = None
                    item["website"] = None
                return item

        return await asyncio.gather(*(enrich(item) for item in items))


async def fetch_page(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = await client.get(
            url,
            follow_redirects=True,
            headers={"User-Agent": "LeadFlowResearch/1.0"},
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
            "ok": False,
            "status": None,
            "url": url,
            "html": "",
            "seconds": round(time.perf_counter() - started, 2),
            "error": str(exc),
        }


def inspect_site(url: str, page: dict[str, Any], business_name: str) -> dict[str, Any]:
    html = page.get("html", "")
    lower = html.lower()
    soup = BeautifulSoup(html, "html.parser")
    visible_text = soup.get_text(" ", strip=True).lower()
    scripts = " ".join(str(x) for x in soup.find_all("script")).lower()

    forms = soup.find_all("form")
    form_text = " ".join(str(x) for x in forms).lower()
    lead_form = bool(forms) and any(k in (form_text + visible_text) for k in [
        "contact", "quote", "estimate", "inquiry", "request", "lead", "get started"
    ])

    booking_markers = [
        "calendly.com", "acuityscheduling.com", "squareup.com/appointments",
        "setmore.com", "simplybook.me", "booksy.com", "mindbodyonline.com",
        "book appointment", "schedule appointment", "book a consultation",
    ]
    chat_markers = ["intercom", "drift.com", "tawk.to", "crisp.chat", "tidio", "zendesk", "livechat", "hubspot"]
    analytics_markers = ["googletagmanager.com", "google-analytics.com", "gtag(", "clarity.ms", "hotjar", "connect.facebook.net"]

    return {
        "website_exists": True,
        "website_working": page.get("ok", False),
        "https": urlparse(url).scheme.lower() == "https",
        "lead_form": lead_form,
        "booking": any(x in lower for x in booking_markers),
        "chatbot": any(x in lower or x in scripts for x in chat_markers),
        "analytics": any(x in scripts or x in lower for x in analytics_markers),
        "slow": page.get("seconds", 0) > 4,
        "broken": not page.get("ok", False),
        "status_code": page.get("status"),
        "response_time": page.get("seconds"),
        "final_url": page.get("url"),
        "business_name_found_on_page": business_name_matches(business_name, visible_text),
    }


def extract_emails(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    values: set[str] = set()
    for link in soup.select('a[href^="mailto:"]'):
        raw = link.get("href", "").replace("mailto:", "").split("?", 1)[0]
        email = clean_email(raw)
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

    for path in ["/contact", "/contact-us", "/about", "/about-us"]:
        target = urljoin(website + "/", path.lstrip("/"))
        try:
            response = await client.get(target, follow_redirects=True, headers={"User-Agent": "LeadFlowResearch/1.0"})
            if response.status_code >= 400:
                continue
            text = response.text[:1_500_000]
            if not business_name_matches(business_name, BeautifulSoup(text, "html.parser").get_text(" ", strip=True)):
                continue
            emails = extract_emails(text)
            if emails:
                return emails[0], target
        except Exception:
            continue
    return None, None


def score(business: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    # 100-point opportunity score. Higher means more actionable commercial opportunity.
    points = 0
    gaps: list[str] = []
    reasons: list[str] = []

    if business.get("phone"):
        points += 10
    else:
        gaps.append("No verified phone")

    if business.get("email"):
        points += 10
    else:
        gaps.append("No verified email")

    if not signals.get("website_exists"):
        points += 30
        gaps.append("Website build")
        reasons.append("No website found; strong website-build prospect.")
    else:
        if signals.get("website_working"):
            points += 5
        else:
            points += 12
            gaps.append("Broken website")
            reasons.append("Website did not return a healthy response.")

        if signals.get("lead_form"):
            points += 4
        else:
            points += 10
            gaps.append("Lead capture")

        if signals.get("booking"):
            points += 3
        else:
            points += 10
            gaps.append("Booking")

        if signals.get("chatbot"):
            points += 2
        else:
            points += 8
            gaps.append("Chat/AI")

        if signals.get("analytics"):
            points += 2
        else:
            points += 5
            gaps.append("Analytics")

        if signals.get("https"):
            points += 5
        else:
            gaps.append("HTTPS")

        if signals.get("slow"):
            points += 5
            gaps.append("Slow site")

    score_value = min(100, points)
    tier = "Very High" if score_value >= 75 else "High" if score_value >= 55 else "Moderate" if score_value >= 35 else "Low"
    prospect_type = "website_build" if not signals.get("website_exists") else "automation_upgrade"

    return {
        "score": score_value,
        "tier": tier,
        "prospect_type": prospect_type,
        "gaps": gaps,
        "reasons": reasons,
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
                        "website_exists": False,
                        "website_working": False,
                        "https": False,
                        "lead_form": False,
                        "booking": False,
                        "chatbot": False,
                        "analytics": False,
                        "slow": False,
                        "broken": False,
                        "status_code": None,
                        "response_time": None,
                        "final_url": None,
                    }
                    item["email"] = None
                else:
                    page = await fetch_page(client, website)
                    signals = inspect_site(website, page, item.get("name") or "")
                    email, source = await find_email(client, website, item.get("name") or "", page.get("html", ""))
                    item["email"] = email
                    item["email_source"] = source

                item["signals"] = signals
                item.update(score(item, signals))
                return item

        results = await asyncio.gather(*(research(x) for x in businesses))

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    return results


@app.get("/")
async def root():
    return {"service": "Lead Flow Intelligence API", "version": APP_VERSION, "status": "online"}


@app.get("/health")
async def health():
    return {"status": "ok", "google_api_configured": bool(GOOGLE_API_KEY), "version": APP_VERSION}


@app.get("/scan")
async def scan(
    city: str = Query(..., min_length=1),
    industry: str = Query(..., min_length=1),
    country: str = Query(..., min_length=1),
):
    results = await run_scan(city.strip(), industry.strip(), country.strip())
    return {
        "success": True,
        "version": APP_VERSION,
        "location": {"city": city.strip(), "country": country.strip()},
        "industry": industry.strip(),
        "count": len(results),
        "results": results,
    }
