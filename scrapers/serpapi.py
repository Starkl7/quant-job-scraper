"""
scrapers/serpapi.py — Google Jobs scraper via SerpAPI.
Returns a normalized DataFrame matching the shared NORMALIZED_SCHEMA.
"""

import os
import re
import time

import requests
import pandas as pd

from config import GJ_TERMS, SERPAPI_DATE_FILTER, SERPAPI_KEY_GROUPS, SERPAPI_DRY_RUN

SERPAPI_URL = "https://serpapi.com/search.json"

NORMALIZED_SCHEMA = [
    "title", "company", "location", "site", "job_url",
    "description", "min_amount", "max_amount", "job_type", "date_posted",
]

# ── Salary parsing ─────────────────────────────────────────────────────────────

_SALARY_NUM_RE = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(k)?', re.IGNORECASE)


def parse_salary(s: str) -> tuple[float | None, float | None]:
    """
    Convert SerpAPI salary string to (min_annual, max_annual) floats.
    Returns (None, None) if unparseable.
    Examples:
      '$124,000 - $177,000 a year' → (124000.0, 177000.0)
      '100K–125K a year'           → (100000.0, 125000.0)
      '$80 - $100 an hour'         → (166400.0, 208000.0)
    """
    if not s:
        return None, None
    hourly = bool(re.search(r'\bhour\b|/hr\b', s, re.I))
    nums: list[float] = []
    for m in _SALARY_NUM_RE.finditer(s.replace(',', '')):
        val = float(m.group(1))
        if m.group(2):
            val *= 1_000
        if hourly:
            if 10 <= val <= 500:
                nums.append(round(val * 2_080))
        else:
            if 10_000 <= val <= 10_000_000:
                nums.append(val)
    if len(nums) >= 2:
        return float(min(nums[:2])), float(max(nums[:2]))
    if len(nums) == 1:
        return nums[0], None
    return None, None


# ── SerpAPI call ───────────────────────────────────────────────────────────────

def scrape_one(q: str, location: str, api_key: str) -> list[dict]:
    """Single SerpAPI google_jobs call. Returns raw jobs_results list."""
    resp = requests.get(
        SERPAPI_URL,
        params={
            "engine":   "google_jobs",
            "q":        q,
            "location": location,
            "chips":    SERPAPI_DATE_FILTER,
            "hl":       "en",
            "api_key":  api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"SerpAPI error: {data['error']}")
    return data.get("jobs_results", [])


# ── Normalisation ──────────────────────────────────────────────────────────────

def to_dataframe(raw_jobs: list[dict]) -> pd.DataFrame:
    """Map SerpAPI jobs_results entries to the shared NORMALIZED_SCHEMA DataFrame."""
    rows = []
    for job in raw_jobs:
        ext        = job.get("detected_extensions", {})
        salary_str = ext.get("salary", "")
        min_amt, max_amt = parse_salary(salary_str)

        apply_options = job.get("apply_options", [])
        job_url = apply_options[0]["link"] if apply_options else job.get("share_link", "")

        rows.append({
            "title":       job.get("title",        ""),
            "company":     job.get("company_name", ""),
            "location":    job.get("location",     ""),
            "site":        "google",
            "job_url":     job_url,
            "description": job.get("description",  ""),
            "min_amount":  min_amt,
            "max_amount":  max_amt,
            "job_type":    ext.get("schedule_type", ""),
            "date_posted": ext.get("posted_at",    ""),
        })
    return pd.DataFrame(rows, columns=NORMALIZED_SCHEMA) if rows else pd.DataFrame(columns=NORMALIZED_SCHEMA)


# ── Full scrape run ────────────────────────────────────────────────────────────

def scrape_all(
    key_groups: list[dict] = SERPAPI_KEY_GROUPS,
    terms: dict[str, str]  = GJ_TERMS,
) -> pd.DataFrame:
    """
    Iterate over key_groups × cities × terms and return a combined DataFrame.
    Each key_group dict: {"key_env": "SERPAPI_KEY_1", "cities": [...]}.
    """
    frames: list[pd.DataFrame] = []

    for group in key_groups:
        api_key = os.getenv(group["key_env"])
        if not api_key:
            print(f"  !! {group['key_env']} not set — skipping {group['cities']}")
            continue

        for city in group["cities"]:
            for term_label, term_q in terms.items():
                if SERPAPI_DRY_RUN:
                    print(f"  [DRY RUN] would search: {term_label:<12} @ {city}")
                    time.sleep(0.1)
                    continue
                try:
                    raw  = scrape_one(term_q, city, api_key)
                    df   = to_dataframe(raw)
                    if not df.empty:
                        frames.append(df)
                    print(f"  {len(raw):>3} results — {term_label:<12} @ {city}")
                except Exception as exc:
                    print(f"  ERROR — {term_label:<12} @ {city}: {exc}")

                time.sleep(1)

    if not frames:
        return pd.DataFrame(columns=NORMALIZED_SCHEMA)

    return pd.concat(frames, ignore_index=True)
