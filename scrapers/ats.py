"""
scrapers/ats.py — Fetchers for direct company ATS endpoints.

Supported ATS types and their public endpoints:
  greenhouse  GET  boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  lever       GET  api.lever.co/v0/postings/{slug}?mode=json&limit=100
  recruitee   GET  {slug}.recruitee.com/api/offers
  pinpoint    GET  {url}  (full URL from ats_companies.py)
  workable    POST apply.workable.com/api/v3/accounts/{slug}/jobs
  workday     POST {tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

All fetchers return a list of normalized job dicts with keys:
  title, company, location, site, job_url, description, date_posted,
  min_amount, max_amount
"""

import html
import re
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from ats_companies import COMPANIES

_TIMEOUT = 15
_SLEEP   = 0.3   # seconds between API calls to avoid rate-limiting

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; job-scraper/1.0)"})

# Noise titles that are not real open positions (talent pools, events, etc.)
# Use specific multi-word phrases to avoid false positives like "Event Coordinator".
_NOISE_PHRASES = (
    "talent pool", "talent community", "talent network",
    "networking event", "virtual challenge", "trading challenge",
    "general interest", "general application",
    "future opportunities", "future openings",
    "open application", "stay connected",
    "hackathon", "competition",
)


def _is_noise(title: str) -> bool:
    t = title.lower()
    return any(p in t for p in _NOISE_PHRASES)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _job(
    title: str,
    company: str,
    location: str,
    url: str,
    description: str | None,
    date_posted: str | None,
) -> dict:
    return {
        "title":       (title or "").strip()[:2000],
        "company":     (company or "").strip()[:2000],
        "location":    (location or "").strip()[:2000],
        "site":        "ats",
        "job_url":     (url or "").strip(),
        "description": _strip_html(description) if description else None,
        "date_posted": date_posted,
        "min_amount":  None,
        "max_amount":  None,
    }


# ── Greenhouse ────────────────────────────────────────────────────────────────

def _fetch_greenhouse(company: str, slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        r = _SESSION.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
    except Exception as exc:
        print(f"    [ATS] {company} greenhouse/{slug}: {exc}")
        return []

    out = []
    for j in r.json().get("jobs", []):
        if _is_noise(j.get("title", "")):
            continue
        location  = j.get("location", {}).get("name", "") or ""
        date      = (j.get("updated_at") or "")[:10] or None
        out.append(_job(
            title=j.get("title", ""),
            company=company,
            location=location,
            url=j.get("absolute_url", ""),
            description=j.get("content", ""),
            date_posted=date,
        ))
    return out


# ── Lever ─────────────────────────────────────────────────────────────────────

def _fetch_lever(company: str, slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=100"
    try:
        r = _SESSION.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
    except Exception as exc:
        print(f"    [ATS] {company} lever/{slug}: {exc}")
        return []

    out = []
    for j in r.json():
        if _is_noise(j.get("text", "")):
            continue
        cats     = j.get("categories") or {}
        location = cats.get("location", "") or ""
        if not location and cats.get("allLocations"):
            location = ", ".join(cats["allLocations"])
        # Lever description: prefer plain text, fall back to HTML
        desc = j.get("descriptionPlain") or j.get("description") or ""
        out.append(_job(
            title=j.get("text", ""),
            company=company,
            location=location,
            url=j.get("hostedUrl", ""),
            description=desc,
            date_posted=None,
        ))
    return out


# ── Recruitee ─────────────────────────────────────────────────────────────────

def _fetch_recruitee(company: str, slug: str) -> list[dict]:
    url = f"https://{slug}.recruitee.com/api/offers"
    try:
        r = _SESSION.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
    except Exception as exc:
        print(f"    [ATS] {company} recruitee/{slug}: {exc}")
        return []

    out = []
    for j in r.json().get("offers", []):
        if _is_noise(j.get("title", "")):
            continue
        city    = j.get("city", "") or ""
        country = j.get("country", "") or ""
        location = ", ".join(p for p in [city, country] if p)
        date = (j.get("created_at") or "")[:10] or None
        out.append(_job(
            title=j.get("title", ""),
            company=company,
            location=location,
            url=j.get("careers_url", ""),
            description=j.get("description", ""),
            date_posted=date,
        ))
    return out


# ── Pinpoint ──────────────────────────────────────────────────────────────────

def _fetch_pinpoint(company: str, url: str) -> list[dict]:
    try:
        r = _SESSION.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
    except Exception as exc:
        print(f"    [ATS] {company} pinpoint/{url}: {exc}")
        return []

    out = []
    for j in r.json().get("data", []):
        if _is_noise(j.get("title", "")):
            continue
        parts    = [j.get("city") or "", j.get("state") or "", j.get("country_name") or ""]
        location = ", ".join(p for p in parts if p)
        out.append(_job(
            title=j.get("title", ""),
            company=company,
            location=location,
            url=j.get("careers_url", ""),
            description=j.get("description", "") or j.get("benefits", ""),
            date_posted=None,
        ))
    return out


# ── Workable ──────────────────────────────────────────────────────────────────

def _fetch_workable(company: str, slug: str) -> list[dict]:
    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    try:
        r = _SESSION.post(
            url,
            json={"query": "", "location": [], "department": [], "worktype": [], "remote": []},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
    except Exception as exc:
        print(f"    [ATS] {company} workable/{slug}: {exc}")
        return []

    out = []
    for j in r.json().get("results", []):
        if _is_noise(j.get("title", "")):
            continue
        city    = j.get("city", "") or ""
        country = j.get("country", "") or ""
        location = ", ".join(p for p in [city, country] if p)
        desc = j.get("description", "") or j.get("full_description", "")
        out.append(_job(
            title=j.get("title", ""),
            company=company,
            location=location,
            url=j.get("url", ""),
            description=desc,
            date_posted=j.get("published_on"),
        ))
    return out


# ── Workday ───────────────────────────────────────────────────────────────────
# Big banks (Citi, Morgan Stanley, Barclays, Deutsche Bank, TD, State Street,
# Northern Trust…) run on Workday's public CXS API. The list endpoint returns
# jobs newest-first but WITHOUT descriptions, so description is left None — the
# scoring phase's fetch_description backfills it. We paginate 20 at a time
# (Workday's hard page cap) and early-stop once postings age past the lookback
# window, which keeps a 1,000+ req bank to a handful of pages per run.

# Big-bank adapters (workday/oracle/radancy) only keep postings from the last
# _RECENT_DAYS days. The ATS workflow runs ~2×/day, so a 5-day window gives
# generous overlap (survives a skipped run) while keeping 1,000+ job boards to
# a handful of pages. Adapters whose feed is date-sorted early-stop on it;
# Radancy's feed is NOT sorted, so it filters per-item instead.
_RECENT_DAYS = 5


def _iso_age(iso: str) -> int | None:
    """Age in days from an ISO 'YYYY-MM-DD' date, or None if unparseable."""
    try:
        return (date.today() - date.fromisoformat(iso[:10])).days
    except Exception:
        return None


_WORKDAY_PAGE     = 20    # Workday enforces max 20 results per CXS request
_WORKDAY_MAX_PAGE = 30    # hard safety cap (30 × 20 = 600 jobs) per company

# "Posted 7 Days Ago" / "Posted 30+ Days Ago" / "Posted Today" / "Posted Yesterday"
_POSTED_RE = re.compile(r"(\d+)\+?\s+day", re.IGNORECASE)


def _workday_posted_age(posted_on: str) -> int | None:
    """Approximate age in days from a Workday 'postedOn' string, or None."""
    if not posted_on:
        return None
    low = posted_on.lower()
    if "today" in low:
        return 0
    if "yesterday" in low:
        return 1
    m = _POSTED_RE.search(low)
    return int(m.group(1)) if m else None


def _fetch_workday(company: str, co: dict) -> list[dict]:
    tenant = co.get("tenant", "")
    wd     = co.get("wd", "")
    site   = co.get("site", "")
    host   = f"{tenant}.{wd}.myworkdayjobs.com"
    api    = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    base   = f"https://{host}/en-US/{site}"

    out: list[dict] = []
    offset = 0
    while offset < _WORKDAY_PAGE * _WORKDAY_MAX_PAGE:
        try:
            r = _SESSION.post(
                api,
                json={"limit": _WORKDAY_PAGE, "offset": offset,
                      "searchText": "", "appliedFacets": {}},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            postings = r.json().get("jobPostings", [])
        except Exception as exc:
            print(f"    [ATS] {company} workday/{tenant}/{site} @off={offset}: {exc}")
            break

        if not postings:
            break

        stop = False
        for j in postings:
            title = j.get("title", "")
            if _is_noise(title):
                continue
            age = _workday_posted_age(j.get("postedOn", ""))
            if age is not None and age > _RECENT_DAYS:
                stop = True          # newest-first ordering → the rest are older too
                break
            date_posted = (
                (date.today() - timedelta(days=age)).isoformat()
                if age is not None else None
            )
            path = j.get("externalPath", "")
            out.append(_job(
                title=title,
                company=company,
                location=j.get("locationsText", ""),
                url=f"{base}{path}" if path else base,
                description=None,     # not in list API; scoring backfills it
                date_posted=date_posted,
            ))

        if stop or len(postings) < _WORKDAY_PAGE:
            break
        offset += _WORKDAY_PAGE
        time.sleep(_SLEEP)

    return out


# ── Oracle Cloud Recruiting ───────────────────────────────────────────────────
# JPMorgan Chase runs on Oracle's Candidate Experience REST API. The finder
# syntax uses literal ';' and ',' which must NOT be URL-encoded, so the query
# string is built by hand rather than via requests' params=. We request
# POSTING_DATES_DESC, so the feed is date-sorted and we early-stop on age.

_ORACLE_PAGE     = 50
_ORACLE_MAX_PAGE = 20   # hard safety cap (20 × 50 = 1,000 jobs) per company


def _fetch_oracle(company: str, co: dict) -> list[dict]:
    host = co.get("host", "")
    site = co.get("site", "")
    api      = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    job_base = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job"

    out: list[dict] = []
    offset = 0
    for _ in range(_ORACLE_MAX_PAGE):
        url = (
            f"{api}?onlyData=true&expand=requisitionList"
            f"&finder=findReqs;siteNumber={site},sortBy=POSTING_DATES_DESC"
            f",limit={_ORACLE_PAGE},offset={offset}"
        )
        try:
            r = _SESSION.get(url, timeout=_TIMEOUT)
            r.raise_for_status()
            items = r.json().get("items", [])
            reqs  = items[0].get("requisitionList", []) if items else []
        except Exception as exc:
            print(f"    [ATS] {company} oracle/{site} @off={offset}: {exc}")
            break

        if not reqs:
            break

        stop = False
        for j in reqs:
            title = j.get("Title", "")
            if _is_noise(title):
                continue
            age = _iso_age(j.get("PostedDate", ""))
            if age is not None and age > _RECENT_DAYS:
                stop = True          # date-sorted → the rest are older too
                break
            jid = j.get("Id", "")
            out.append(_job(
                title=title,
                company=company,
                location=j.get("PrimaryLocation", ""),
                url=f"{job_base}/{jid}" if jid else job_base,
                description=None,     # detail needs a per-job call; scoring backfills
                date_posted=j.get("PostedDate"),
            ))

        if stop or len(reqs) < _ORACLE_PAGE:
            break
        offset += _ORACLE_PAGE
        time.sleep(_SLEEP)

    return out


# ── Radancy (TalentBrew) ──────────────────────────────────────────────────────
# Capital One runs on Radancy. The search-results endpoint returns a JSON
# envelope whose 'results' field is an HTML fragment of <li> job cards. The
# feed is NOT date-sorted (recent postings are scattered across pages), so we
# CANNOT early-stop — we page through with a safety cap and keep only the
# per-item postings inside the recency window.

_RADANCY_PAGE     = 100
_RADANCY_MAX_PAGE = 20   # 20 × 100 = 2,000 jobs — covers Capital One's full board

_RADANCY_HREF_RE = re.compile(r'href="(/job/[^"]+)"')
_RADANCY_TITLE_RE = re.compile(r"<h2>([^<]+)</h2>")
_RADANCY_DATE_RE = re.compile(r'job-date-posted">([^<]+)<')
_RADANCY_LOC_RE  = re.compile(r'job-location">([^<]*)<')


def _fetch_radancy(company: str, base: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, _RADANCY_MAX_PAGE + 1):
        url = (
            f"{base}/search-jobs/results?ActiveFacetID=0&CurrentPage={page}"
            f"&RecordsPerPage={_RADANCY_PAGE}&SearchType=5"
            f"&SearchResultsModuleName=Search+Results"
            f"&SearchFiltersModuleName=Search+Filters"
        )
        try:
            r = _SESSION.get(url, headers={"X-Requested-With": "XMLHttpRequest"},
                             timeout=_TIMEOUT)
            r.raise_for_status()
            frag = r.json().get("results", "")
        except Exception as exc:
            print(f"    [ATS] {company} radancy @page={page}: {exc}")
            break

        cards = frag.split("<li>")[1:]
        if not cards:
            break

        for c in cards:
            mh = _RADANCY_HREF_RE.search(c)
            mt = _RADANCY_TITLE_RE.search(c)
            if not mh or not mt:
                continue
            title = html.unescape(mt.group(1)).strip()
            if _is_noise(title):
                continue
            md = _RADANCY_DATE_RE.search(c)
            date_iso, age = None, None
            if md:
                try:
                    dt = datetime.strptime(md.group(1).strip(), "%m/%d/%Y").date()
                    date_iso, age = dt.isoformat(), (date.today() - dt).days
                except ValueError:
                    pass
            if age is not None and age > _RECENT_DAYS:
                continue             # NOT sorted → skip this one, keep scanning
            ml = _RADANCY_LOC_RE.search(c)
            out.append(_job(
                title=title,
                company=company,
                location=html.unescape(ml.group(1)).strip() if ml else "",
                url=f"{base}{mh.group(1)}",
                description=None,
                date_posted=date_iso,
            ))

        if len(cards) < _RADANCY_PAGE:
            break
        time.sleep(_SLEEP)

    return out


# ── Dispatch ──────────────────────────────────────────────────────────────────

_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever":      _fetch_lever,
    "recruitee":  _fetch_recruitee,
    "pinpoint":   _fetch_pinpoint,
    "workable":   _fetch_workable,
    "workday":    _fetch_workday,
    "oracle":     _fetch_oracle,
    "radancy":    _fetch_radancy,
}


def fetch_all() -> pd.DataFrame:
    """
    Poll every company in ats_companies.COMPANIES and return a combined DataFrame.
    Rows use the same column schema as the JobSpy / SerpAPI scrapers so that
    apply_filters() and push_job() work without modification.
    """
    total    = len(COMPANIES)
    all_jobs: list[dict] = []

    for i, co in enumerate(COMPANIES, 1):
        name = co["name"]
        ats  = co["ats"]
        slug = co.get("slug", "")
        url  = co.get("url", "")
        if ats == "pinpoint":
            label = url
        elif ats == "workday":
            label = f"workday/{co.get('tenant','')}/{co.get('site','')}"
        elif ats == "oracle":
            label = f"oracle/{co.get('host','')}/{co.get('site','')}"
        elif ats == "radancy":
            label = f"radancy/{url}"
        else:
            label = f"{ats}/{slug}"

        print(f"  [{i:02d}/{total}] {name:<28} ({label})", end="", flush=True)

        fetcher = _FETCHERS.get(ats)
        if fetcher is None:
            print(f"  — unknown ATS '{ats}', skipping")
            continue

        try:
            if ats in ("pinpoint", "radancy"):
                jobs = fetcher(name, url)
            elif ats in ("workday", "oracle"):
                jobs = fetcher(name, co)
            else:
                jobs = fetcher(name, slug)
        except Exception as exc:
            print(f"  — unexpected error: {exc}")
            jobs = []

        print(f"  → {len(jobs)} listings")
        all_jobs.extend(jobs)
        time.sleep(_SLEEP)

    if not all_jobs:
        return pd.DataFrame()

    return pd.DataFrame(all_jobs)
