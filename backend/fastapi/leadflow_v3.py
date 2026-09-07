import asyncio
import csv
import io
import re
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

VERSION = "leadflow-fastapi-v3.0.1-complete-pipeline-fixed"
UA = "LeadFlow/3.0 (+https://leadflowautomations.github.io/)"
TIMEOUT = 15.0
CONCURRENCY = 6
NOMINATIM_DELAY = 1.1
JOBS: dict[str, dict[str, Any]] = {}

INDUSTRIES = {
    "real estate": ["real estate", "realty", "realtor", "properties", "property management", "commercial real estate", "residential real estate"],
    "law": ["law firm", "lawyer", "attorney", "legal services"],
    "dentist": ["dentist", "dental clinic", "orthodontist"],
    "restaurant": ["restaurant", "cafe", "bistro"],
    "salon": ["hair salon", "beauty salon", "barber", "salon"],
    "auto repair": ["auto repair", "car repair", "mechanic", "automotive repair"],
}

app = FastAPI(title="Lead Flow Complete Intelligence API", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://leadflowautomations.github.io", "http://localhost:5500", "http://127.0.0.1:5500"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def toks(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def clean_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    value = value if re.match(r"https?://", value, re.I) else "https://" + value
    try:
        parsed = urlparse(value)
        if not parsed.netloc or parsed.hostname in {"google.com", "bing.com", "duckduckgo.com"}:
            return None
        return value.rstrip("/")
    except Exception:
        return None


def clean_email(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower().replace("mailto:", "").split("?")[0]
    return value if re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value) else None


def clean_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return value.strip() if 10 <= len(digits) <= 15 and len(set(digits)) > 1 else None


def business_match(name: str, text: str) -> bool:
    required = {x for x in toks(name) if len(x) > 2}
    words = toks(text)
    return bool(required) and len(required & words) >= max(1, min(2, len(required)))


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = "|".join(sorted(toks(row.get("name", "")))) + "|" + re.sub(r"[^a-z0-9]", "", row.get("address", "").lower())[:60]
        if key not in output:
            output[key] = row
        else:
            for field in ("website", "phone", "email", "address"):
                if not output[key].get(field) and row.get(field):
                    output[key][field] = row[field]
    return list(output.values())


async def geocode(client: httpx.AsyncClient, city: str, country: str):
    response = await client.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": f"{city}, {country}", "format": "jsonv2", "limit": 1},
        headers={"User-Agent": UA},
    )
    response.raise_for_status()
    data = response.json()
    return (float(data[0]["lat"]), float(data[0]["lon"])) if data else None


async def nominatim_search(client: httpx.AsyncClient, query: str, lat: float, lon: float, delta: float):
    await asyncio.sleep(NOMINATIM_DELAY)
    half = delta / 2
    response = await client.get(
        "https://nominatim.openstreetmap.org/search",
        params={
            "q": query,
            "format": "jsonv2",
            "limit": 40,
            "viewbox": f"{lon-half},{lat+half},{lon+half},{lat-half}",
            "bounded": 1,
            "layer": "poi",
            "addressdetails": 1,
        },
        headers={"User-Agent": UA, "Referer": "https://leadflowautomations.github.io/"},
    )
    response.raise_for_status()
    return response.json()


async def discover(city: str, industry: str, country: str, job: dict[str, Any]) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        center = await geocode(client, city, country)
        if not center:
            return []
        lat, lon = center
        terms = INDUSTRIES.get(industry.lower().strip(), [industry])
        delta = 0.10 if abs(lat) > 25 else 0.06
        queries = [(term, lat + (iy - 1) * delta, lon + (ix - 1) * delta) for iy in range(3) for ix in range(3) for term in terms]
        rows: list[dict[str, Any]] = []
        job.update(stage="collect", message=f"Collecting candidates across {len(queries)} local search windows…", collection_queries=len(queries), updated_at=time.time())
        for completed, (query, y, x) in enumerate(queries, 1):
            try:
                for result in await nominatim_search(client, query, y, x, delta):
                    name = (result.get("name") or result.get("display_name", "").split(",")[0]).strip()
                    if not name:
                        continue
                    address = result.get("address") or {}
                    extra = result.get("extratags") or {}
                    rows.append({
                        "source_id": f"osm:{result.get('osm_type')}:{result.get('osm_id')}",
                        "name": name,
                        "address": ", ".join(str(address[k]) for k in ("house_number", "road", "city", "state", "postcode") if address.get(k)) or result.get("display_name"),
                        "lat": result.get("lat"),
                        "lon": result.get("lon"),
                        "website": clean_url(extra.get("contact:website") or extra.get("website")),
                        "phone": clean_phone(extra.get("contact:phone") or extra.get("phone")),
                        "email": clean_email(extra.get("contact:email") or extra.get("email")),
                        "source": "OpenStreetMap",
                        "industry": industry,
                    })
            except Exception as exc:
                job["errors"] += 1
                job["last_error"] = f"discovery: {str(exc)[:250]}"
            job.update(collection_completed=completed, discovered=len(dedupe(rows)), updated_at=time.time())
        return dedupe(rows)


def extract_emails(html: str) -> list[str]:
    return list(dict.fromkeys(filter(None, [clean_email(x) for x in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html)])))


def extract_phones(html: str) -> list[str]:
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    return list(dict.fromkeys(filter(None, [clean_phone(x) for x in re.findall(r"(?:\+?\d[\d\s().-]{8,}\d)", text)])))


async def fetch_page(client: httpx.AsyncClient, url: str):
    started = time.perf_counter()
    try:
        response = await client.get(url, follow_redirects=True, headers={"User-Agent": UA})
        return response.status_code, str(response.url), response.text[:2_000_000], time.perf_counter() - started
    except Exception:
        return 599, url, "", time.perf_counter() - started


def site_signals(url: str, html: str, status: int, seconds: float, name: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    low = html.lower()
    lower_text = text.lower()
    scripts = " ".join(map(str, soup.find_all("script"))).lower()
    forms = soup.find_all("form")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    description = description_tag.get("content", "") if description_tag else ""
    return {
        "website_exists": True,
        "website_working": status < 400,
        "https": urlparse(url).scheme == "https",
        "business_match": business_match(name, text),
        "lead_form": bool(forms),
        "booking": any(x in low for x in ["calendly.com", "acuityscheduling", "book appointment", "schedule appointment", "book a consultation"]),
        "chatbot": any(x in low + scripts for x in ["intercom", "tawk.to", "crisp.chat", "tidio", "zendesk", "livechat"]),
        "analytics": any(x in low + scripts for x in ["googletagmanager", "google-analytics", "gtag(", "clarity.ms", "hotjar"]),
        "qualification": any(x in lower_text for x in ["budget", "timeframe", "property type", "project type", "service needed", "preferred date", "how can we help"]),
        "seo": bool(title and description and len(title) >= 10),
        "social": any(x in low for x in ["facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com"]),
        "reviews": any(x in lower_text for x in ["reviews", "testimonials", "client stories", "google reviews", "yelp"]),
        "slow": seconds > 4,
        "status_code": status,
        "response_time": round(seconds, 2),
        "title": title,
        "description": description[:300],
        "emails_found": extract_emails(html)[:10],
        "phones_found": extract_phones(html)[:10],
    }


async def find_contacts(client: httpx.AsyncClient, website: str, name: str, home_html: str):
    pages = [website] + [website + "/" + path for path in ["contact", "contact-us", "about", "about-us", "get-in-touch"]]
    found = []
    for url in pages:
        try:
            if url == website and home_html:
                html = home_html
                final_url = website
                status = 200
            else:
                response = await client.get(url, follow_redirects=True, headers={"User-Agent": UA})
                status = response.status_code
                html = response.text[:1_500_000]
                final_url = str(response.url)
            if status >= 400:
                continue
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            if not business_match(name, text):
                continue
            found.extend(("email", email, final_url) for email in extract_emails(html))
            found.extend(("phone", phone, final_url) for phone in extract_phones(html))
        except Exception:
            continue
    return found


def verify_contact(item: dict[str, Any], found: list[tuple[str, str, str]]):
    domain = (urlparse(item.get("website") or "").hostname or "").lower().removeprefix("www.")
    email = item.get("email")
    phone = item.get("phone")
    evidence = []
    if email:
        evidence.append("discovery email")
    if phone:
        evidence.append("discovery phone")
    for kind, value, source in found:
        if kind == "email" and not email:
            email = value
            evidence.append("business website email")
        if kind == "phone" and not phone:
            phone = value
            evidence.append("business website phone")
    email_domain = email.split("@")[-1].lower() if email and "@" in email else ""
    domain_match = bool(domain and email_domain == domain)
    if domain_match:
        evidence.append("email domain matches website")
    return email, phone, {
        "email": bool(email),
        "phone": bool(phone),
        "email_domain_match": domain_match,
        "website_source": any("business website" in x for x in evidence),
        "evidence": evidence,
    }


def score(item: dict[str, Any], signals: dict[str, Any]):
    gaps = []
    points = 0
    checks = [
        ("website", not signals.get("website_working"), 18),
        ("contact", not (item.get("phone") and item.get("email")), 10),
        ("booking", not signals.get("booking"), 16),
        ("lead capture", not signals.get("lead_form"), 14),
        ("qualification", not signals.get("qualification"), 12),
        ("AI/live chat", not signals.get("chatbot"), 10),
        ("analytics", not signals.get("analytics"), 8),
        ("SEO", not signals.get("seo"), 7),
        ("social", not signals.get("social"), 3),
        ("reviews", not signals.get("reviews"), 2),
    ]
    for label, gap, weight in checks:
        if gap:
            points += weight
            gaps.append(label)
    points = min(100, points)
    tier = "Very High" if points >= 75 else "High" if points >= 55 else "Moderate" if points >= 35 else "Low"
    return points, tier, gaps


def automation(item: dict[str, Any]):
    score_value = int(item.get("score") or 0)
    ready = bool(item.get("verified_business") and (item.get("phone") or item.get("email")))
    if score_value >= 75 and ready:
        action = "PRIORITY_OUTREACH"
    elif score_value >= 55 and ready:
        action = "OUTREACH"
    elif score_value >= 35:
        action = "RESEARCH_MORE"
    else:
        action = "NURTURE"
    return {
        "action": action,
        "outreach_ready": ready,
        "next_action": "Contact using verified public channel" if ready else "Find an additional public contact source",
        "reason": "High confirmed opportunity gaps with verified business identity" if ready and score_value >= 55 else "Needs additional evidence before outreach",
    }


async def process_candidate(client: httpx.AsyncClient, item: dict[str, Any], semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            website = item.get("website")
            signals: dict[str, Any] = {"website_exists": False, "website_working": False, "business_match": False}
            found = []
            if website:
                status, final_url, html, seconds = await fetch_page(client, website)
                if html:
                    signals = site_signals(final_url, html, status, seconds, item["name"])
                if html and signals.get("business_match"):
                    found = await find_contacts(client, final_url, item["name"], html)
            email, phone, contact_verification = verify_contact(item, found)
            item.update(email=email, phone=phone, contact_verification=contact_verification, signals=signals)
            verified = bool(signals.get("business_match")) if website else bool(item.get("name") and item.get("address"))
            item["verified_business"] = verified
            item["verification"] = {
                "identity": verified,
                "website_business_match": bool(signals.get("business_match")),
                "source": "OpenStreetMap + business website" if website else "OpenStreetMap",
                "confidence": "high" if verified and (signals.get("business_match") or website) else "medium",
            }
            score_value, tier, gaps = score(item, signals)
            item.update(score=score_value, tier=tier, gaps=gaps, research_status="complete")
            item["automation"] = automation(item)
            return item
        except Exception as exc:
            # A single bad website/contact lookup must never erase the candidate.
            item["research_status"] = "error"
            item["error"] = str(exc)[:300]
            item["verified_business"] = False
            item["signals"] = item.get("signals") or {"website_exists": bool(item.get("website")), "website_working": False, "business_match": False}
            score_value, tier, gaps = score(item, item["signals"])
            item.update(score=score_value, tier=tier, gaps=gaps)
            item["automation"] = automation(item)
            return item


async def process(job_id: str, city: str, industry: str, country: str):
    job = JOBS[job_id]
    started = time.perf_counter()
    try:
        job.update(status="discovering", stage="discover", message="Locating search area…", updated_at=time.time())
        rows = await discover(city, industry, country, job)
        job.update(candidate_count=len(rows), status="verifying", stage="verify", message=f"Collected {len(rows)} candidates. Verifying businesses and contacts…", updated_at=time.time())
        results: list[dict[str, Any]] = []
        semaphore = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for start in range(0, len(rows), CONCURRENCY):
                batch = await asyncio.gather(*(process_candidate(client, row, semaphore) for row in rows[start:start + CONCURRENCY]), return_exceptions=False)
                results.extend(batch)
                results.sort(key=lambda row: (row.get("score", 0), int(bool(row.get("verified_business"))), int(bool(row.get("email")) or bool(row.get("phone")))), reverse=True)
                for rank, row in enumerate(results, 1):
                    row["rank"] = rank
                job.update(processed=len(results), results=results, errors=sum(1 for row in results if row.get("research_status") == "error"), message=f"Researched {len(results)} of {len(rows)} candidates…", updated_at=time.time())
        verified_count = sum(bool(row.get("verified_business")) for row in results)
        job.update(status="complete", stage="automate", message=f"Pipeline complete — {verified_count} businesses verified, researched, scored, ranked and actioned.", duration_seconds=round(time.perf_counter() - started, 2), updated_at=time.time())
    except Exception as exc:
        job.update(status="failed", stage="error", message="Pipeline failed", error=str(exc)[:500], updated_at=time.time())


@app.get("/")
async def root():
    return {"service": "Lead Flow Complete Pipeline", "version": VERSION, "pipeline": ["discover", "collect", "verify", "contact_verify", "research", "score", "rank", "automate"], "google_api_required": False}


@app.get("/health")
async def health():
    return {"status": "ok", "version": VERSION, "active_jobs": sum(job["status"] not in ("complete", "failed") for job in JOBS.values())}


@app.post("/research-jobs")
async def create(background_tasks: BackgroundTasks, city: str = Query(...), industry: str = Query(...), country: str = Query(...)):
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"job_id": job_id, "city": city.strip(), "country": country.strip(), "industry": industry.strip(), "status": "queued", "stage": "queued", "message": "Queued", "candidate_count": 0, "processed": 0, "errors": 0, "results": [], "created_at": time.time(), "updated_at": time.time()}
    background_tasks.add_task(process, job_id, city.strip(), industry.strip(), country.strip())
    return {"ok": True, "job_id": job_id, "status": "queued", "poll_url": f"/research-jobs/{job_id}"}


@app.get("/research-jobs/{job_id}")
async def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Research job not found")
    return JOBS[job_id]


@app.get("/research-jobs/{job_id}/automation")
async def automation_queue(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Research job not found")
    results = JOBS[job_id].get("results", [])
    queue = [row for row in results if row.get("automation", {}).get("outreach_ready")]
    return {"job_id": job_id, "queue": queue, "total_ready": len(queue)}


@app.get("/research-jobs/{job_id}/csv")
async def export_csv(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Research job not found")
    rows = JOBS[job_id].get("results", [])
    output = io.StringIO()
    fields = ["rank", "name", "address", "website", "phone", "email", "verified_business", "score", "tier", "research_status", "automation_action", "outreach_ready"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "rank": row.get("rank"), "name": row.get("name"), "address": row.get("address"), "website": row.get("website"),
            "phone": row.get("phone"), "email": row.get("email"), "verified_business": row.get("verified_business"),
            "score": row.get("score"), "tier": row.get("tier"), "research_status": row.get("research_status"),
            "automation_action": row.get("automation", {}).get("action"), "outreach_ready": row.get("automation", {}).get("outreach_ready"),
        })
    return output.getvalue()
