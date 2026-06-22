"""
scrapers/ats.py — Fetchers for direct company ATS endpoints.

Supported ATS types and their public endpoints:
  greenhouse  GET  boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  lever       GET  api.lever.co/v0/postings/{slug}?mode=json&limit=100
  recruitee   GET  {slug}.recruitee.com/api/offers
  pinpoint    GET  {url}  (full URL from ats_companies.py)
  workable    POST apply.workable.com/api/v3/accounts/{slug}/jobs

All fetchers return a list of normalized job dicts with keys:
  title, company, location, site, job_url, description, date_posted,
  min_amount, max_amount
"""

import html
import re
import time

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


# ── Dispatch ──────────────────────────────────────────────────────────────────

_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever":      _fetch_lever,
    "recruitee":  _fetch_recruitee,
    "pinpoint":   _fetch_pinpoint,
    "workable":   _fetch_workable,
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
        label = url if ats == "pinpoint" else f"{ats}/{slug}"

        print(f"  [{i:02d}/{total}] {name:<28} ({label})", end="", flush=True)

        fetcher = _FETCHERS.get(ats)
        if fetcher is None:
            print(f"  — unknown ATS '{ats}', skipping")
            continue

        try:
            if ats == "pinpoint":
                jobs = fetcher(name, url)
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
