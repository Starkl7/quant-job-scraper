"""
scrapers/ats.py — Fetchers for direct company ATS endpoints.

Supported ATS types and their public endpoints:
  greenhouse  GET  boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  lever       GET  api.lever.co/v0/postings/{slug}?mode=json&limit=100
  recruitee   GET  {slug}.recruitee.com/api/offers
  pinpoint    GET  {url}  (full URL from ats_companies.py)
  workable    POST apply.workable.com/api/v3/accounts/{slug}/jobs
  workday     POST {tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  oracle      GET  {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
  radancy     GET  {url}/search-jobs/results
  eightfold   GET  {host}/api/apply/v2/jobs?domain={domain}&sort_by=timestamp
  phenom      POST {url}/widgets  (ddoKey=refineSearch)
  avature     GET  {url}/SearchJobs?jobOffset={n}  (server-rendered HTML)

All fetchers return a list of normalized job dicts with keys:
  title, company, location, site, job_url, description, date_posted,
  min_amount, max_amount
"""

import html
import re
import time
from datetime import date, datetime, timedelta, timezone

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

# Card boundary: matches both bare "<li>" (Capital One) and "<li class=…>" (ING).
_RADANCY_CARD_RE = re.compile(r"<li[\s>]")
# Job link, allowing an optional locale prefix: "/job/…" (Capital One) or
# "/en/job/…", "/en-us/job/…" (ING and other localized Radancy portals).
_RADANCY_HREF_RE = re.compile(r'href="(/(?:[a-z]{2}(?:[-_][a-z]{2})?/)?job/[^"]+)"', re.I)
# <h2> may carry classes (ING) or be bare (Capital One).
_RADANCY_TITLE_RE = re.compile(r"<h2[^>]*>([^<]+)</h2>")
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

        cards = _RADANCY_CARD_RE.split(frag)[1:]
        if not cards:
            break

        page_jobs = 0
        for c in cards:
            mh = _RADANCY_HREF_RE.search(c)
            mt = _RADANCY_TITLE_RE.search(c)
            if not mh or not mt:
                continue             # nested meta <li> or non-job chunk
            page_jobs += 1
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

        # End of results when a page yields fewer job cards than requested.
        # (Count real job cards, not raw <li> splits — cards nest <li> metadata.)
        if page_jobs < _RADANCY_PAGE:
            break
        time.sleep(_SLEEP)

    return out


# ── Eightfold AI ──────────────────────────────────────────────────────────────
# HSBC's current careers site (portal.careers.hsbc.com) runs on Eightfold —
# NOT the legacy Avature portal it is migrating off. Unlike the other bank
# adapters we do NOT recency-filter here: HSBC bulk-migrated its board into
# Eightfold, so t_create reflects the migration date, not the posting date —
# open quant/graduate roles carry months-old t_create and would be wrongly
# aged out. Instead we keyword-target the API's `query` param (bounded, relevant
# result sets) and let Notion dedup identify what's new, exactly like the
# SerpAPI/JobSpy layers. Descriptions aren't in the list response → left None.

_EIGHTFOLD_PAGE     = 10   # Eightfold hard-caps the page size at 10 (num>10 is
                           # silently ignored); paginate via `start` instead
_EIGHTFOLD_MAX_PAGE = 12   # per query (12 × 10 = 120 jobs) safety cap

# Role-targeted queries covering the scraper's mandate. Fuzzy-matched by
# Eightfold; the downstream title gate + scoring drop anything off-target.
_EIGHTFOLD_QUERIES = (
    "quantitative", "quant trader", "quantitative analyst",
    "quantitative researcher", "graduate programme",
)


def _fetch_eightfold(company: str, co: dict) -> list[dict]:
    host    = co.get("host", "")
    domain  = co.get("domain", "")
    queries = co.get("queries", _EIGHTFOLD_QUERIES)
    api = f"https://{host}/api/apply/v2/jobs"

    out: list[dict] = []
    seen: set = set()
    for q in queries:
        for page in range(_EIGHTFOLD_MAX_PAGE):
            try:
                r = _SESSION.get(
                    api,
                    params={"domain": domain, "query": q,
                            "start": page * _EIGHTFOLD_PAGE,
                            "num": _EIGHTFOLD_PAGE, "sort_by": "timestamp"},
                    timeout=_TIMEOUT,
                )
                r.raise_for_status()
                positions = r.json().get("positions", [])
            except Exception as exc:
                print(f"    [ATS] {company} eightfold/{domain} q={q!r}: {exc}")
                break

            if not positions:
                break

            for j in positions:
                jid = j.get("id")
                if jid in seen:          # de-dupe across overlapping queries
                    continue
                seen.add(jid)
                title = j.get("name", "")
                if _is_noise(title):
                    continue
                ts = j.get("t_create")
                date_iso = (
                    datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                    if ts else None
                )
                location = j.get("location") or ", ".join(j.get("locations", []) or [])
                out.append(_job(
                    title=title,
                    company=company,
                    location=location,
                    url=j.get("canonicalPositionUrl", ""),
                    description=j.get("job_description"),   # empty in list → None
                    date_posted=date_iso,
                ))

            if len(positions) < _EIGHTFOLD_PAGE:
                break
            time.sleep(_SLEEP)

    return out


# ── Phenom People ─────────────────────────────────────────────────────────────
# U.S. Bank (careers.usbank.com) and RBC (jobs.rbc.com) both run Phenom, which
# exposes a POST /widgets "refineSearch" endpoint. It supports date-sorting and
# from/size pagination (size caps at 100), so — like the workday/oracle adapters
# — we pull newest-first and early-stop on age. lang/country in the body are
# ignored by the endpoint (any values return the same board). A short
# descriptionTeaser ships inline; scoring backfills the full text.

_PHENOM_PAGE     = 100  # Phenom accepts up to 100 results per request
_PHENOM_MAX_PAGE = 15   # hard safety cap (15 × 100 = 1,500 jobs) per company


def _fetch_phenom(company: str, co: dict) -> list[dict]:
    base    = co.get("url", "").rstrip("/")
    lang    = co.get("lang", "en_us")
    country = co.get("country", "us")
    api = f"{base}/widgets"

    out: list[dict] = []
    frm = 0
    for _ in range(_PHENOM_MAX_PAGE):
        body = {
            "lang": lang, "deviceType": "desktop", "country": country,
            "pageName": "search-results", "ddoKey": "refineSearch", "stateInfo": {},
            "eventType": "search", "jobs": True, "keywords": "", "location": "",
            "locationData": {}, "size": _PHENOM_PAGE, "from": frm,
            "jobsWithoutTypeaheadKeywords": False, "clickId": "",
            "searchByLocation": False, "global": False, "selected_fields": {},
            "sort": {"order": "desc", "field": "postedDate"},
        }
        try:
            r = _SESSION.post(api, json=body, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json().get("refineSearch", {}).get("data", {})
            jobs = data.get("jobs", [])
        except Exception as exc:
            print(f"    [ATS] {company} phenom/{base} @from={frm}: {exc}")
            break

        if not jobs:
            break

        stop = False
        for j in jobs:
            title = j.get("title", "")
            if _is_noise(title):
                continue
            age = _iso_age(j.get("postedDate", ""))
            if age is not None and age > _RECENT_DAYS:
                stop = True          # date-sorted → the rest are older too
                break
            url = j.get("applyUrl") or j.get("jobSeoUrl") or ""
            if url.endswith("/apply"):
                url = url[:-len("/apply")]
            out.append(_job(
                title=title,
                company=company,
                location=j.get("cityStateCountry") or j.get("location", ""),
                url=url,
                description=j.get("descriptionTeaser"),   # short teaser; scoring backfills
                date_posted=(j.get("postedDate") or "")[:10] or None,
            ))

        if stop or len(jobs) < _PHENOM_PAGE:
            break
        frm += _PHENOM_PAGE
        time.sleep(_SLEEP)

    return out


# ── Avature ───────────────────────────────────────────────────────────────────
# Macquarie Group (recruitment.macquarie.com) runs a classic Avature portal that
# server-renders results as <article class="article--result"> cards — a plain
# GET returns them (no JS needed). Paginated via jobOffset (9/page, fixed) and
# date-sorted newest-first, so we early-stop on age like workday/oracle.
# NB: mq.wd3.myworkdayjobs.com is Macquarie *University*, a different entity —
# the Avature portal is the actual Macquarie Group board. Descriptions live on
# the JobDetail page (per-job) → left None for scoring to backfill.

_AVATURE_PAGE     = 9    # portal-fixed page size (jobRecordsPerPage is ignored)
_AVATURE_MAX_PAGE = 30   # hard safety cap (30 × 9 = 270 jobs) per company

_AVATURE_CARD_RE  = re.compile(r'<article class="article article--result')
_AVATURE_JOB_RE   = re.compile(r'JobDetail\?jobId=(\d+)"[^>]*>\s*([^<]+?)\s*</a>')
_AVATURE_LOC_RE   = re.compile(r'icon-location\.svg.*?<p>\s*([^<]+?)\s*</p>', re.S)
_AVATURE_DATE_RE  = re.compile(r'(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})')


def _fetch_avature(company: str, co: dict) -> list[dict]:
    base = co.get("url", "").rstrip("/")

    out: list[dict] = []
    offset = 0
    for _ in range(_AVATURE_MAX_PAGE):
        try:
            r = _SESSION.get(f"{base}/SearchJobs?jobOffset={offset}", timeout=_TIMEOUT)
            r.raise_for_status()
            page = r.text
        except Exception as exc:
            print(f"    [ATS] {company} avature/{base} @off={offset}: {exc}")
            break

        cards = _AVATURE_CARD_RE.split(page)[1:]
        if not cards:
            break

        stop, page_jobs = False, 0
        for c in cards:
            end = c.find("</article>")
            if end != -1:
                c = c[:end]
            mj = _AVATURE_JOB_RE.search(c)
            if not mj:
                continue
            page_jobs += 1
            jid   = mj.group(1)
            title = html.unescape(mj.group(2)).strip()
            if _is_noise(title):
                continue
            md = _AVATURE_DATE_RE.search(c)
            date_iso, age = None, None
            if md:
                try:
                    dt = datetime.strptime(md.group(1), "%d %b %Y").date()
                    date_iso, age = dt.isoformat(), (date.today() - dt).days
                except ValueError:
                    pass
            if age is not None and age > _RECENT_DAYS:
                stop = True          # date-sorted → the rest are older too
                break
            ml = _AVATURE_LOC_RE.search(c)
            out.append(_job(
                title=title,
                company=company,
                location=html.unescape(ml.group(1)).strip() if ml else "",
                url=f"{base}/JobDetail?jobId={jid}",
                description=None,
                date_posted=date_iso,
            ))

        if stop or page_jobs < _AVATURE_PAGE:
            break
        offset += _AVATURE_PAGE
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
    "phenom":     _fetch_phenom,
    "eightfold":  _fetch_eightfold,
    "avature":    _fetch_avature,
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
        elif ats == "eightfold":
            label = f"eightfold/{co.get('domain','')}"
        elif ats == "phenom":
            label = f"phenom/{url}"
        elif ats == "avature":
            label = f"avature/{url}"
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
            elif ats in ("workday", "oracle", "eightfold", "phenom", "avature"):
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
