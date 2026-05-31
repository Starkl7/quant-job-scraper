"""
Job scraper — pulls quant/trading roles globally via JobSpy (LinkedIn +
Indeed) and pushes net-new listings into the "Full-Time Job Applications"
Notion database.

Sources: LinkedIn and Indeed only.
  • Glassdoor  — blocked by Cloudflare (403 on every request)
  • ZipRecruiter — blocked by Cloudflare (403 on every request)
  • Google Jobs — requires JS execution; cursor-based scraper broken upstream

Deduplication:
  1. Within-run: normalized (role, company, city) collapses cross-board dupes.
  2. Title+company: same role posted across multiple cities → keep one.
  3. Cross-run: Notion DB is queried for existing dedup keys before each push.

Early-career filter: hard-excludes senior/lead/VP/director titles; keeps
everything else (including unlabelled new-grad quant roles at top firms).

Required env vars:
  NOTION_TOKEN  — Notion integration secret
  NOTION_DB_ID  — Target database ID (without dashes)
"""

import os
import re
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from jobspy import scrape_jobs

# ── Config ────────────────────────────────────────────────────────────────────

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID", "")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ── Location config ───────────────────────────────────────────────────────────
# Each tuple: (location_string, country_indeed)
# Glassdoor requires city-level locations (rejects country strings).
_US_CITIES: list[tuple[str, str]] = [
    ("New York, NY",       "USA"),   # Wall Street, hedge funds, bulge brackets
    ("Chicago, IL",        "USA"),   # Citadel, DRW, Jump, Virtu, CME
    ("San Francisco, CA",  "USA"),   # tech-adjacent quant, fintech
    ("Boston, MA",         "USA"),   # Fidelity, State Street, Two Sigma office
    ("Stamford, CT",       "USA"),   # Bridgewater, AQR, Point72, hedge fund corridor
    ("Jersey City, NJ",    "USA"),   # Goldman, JPMorgan, bank back-offices
    ("Austin, TX",         "USA"),   # Citadel, Jane Street expansion hub
    ("Los Angeles, CA",    "USA"),   # hedge funds, Western Asset, Ares
    ("Seattle, WA",        "USA"),   # tech-quant crossover, DE Shaw, Amazon
    ("Miami, FL",          "USA"),   # growing finance hub, Citadel HQ
    ("Charlotte, NC",      "USA"),   # Bank of America, Wells Fargo
]
_INTL_CITIES: list[tuple[str, str]] = [
    ("London, United Kingdom", "UK"),
    ("Hong Kong",              "Hong Kong"),
    ("Singapore",              "Singapore"),
    ("Zurich, Switzerland",    "Switzerland"),
    ("Amsterdam, Netherlands", "Netherlands"),
    ("Toronto, Canada",        "Canada"),
    ("Sydney, Australia",      "Australia"),
]
_ALL_CITIES = _US_CITIES + _INTL_CITIES

# ── Search terms ──────────────────────────────────────────────────────────────
_RESEARCHER_TERM = (
    '("quantitative researcher" OR "quant researcher" OR "quantitative analyst" '
    'OR "quant analyst" OR "quantitative strategist" OR "quant strategist") -developer'
)
_TRADER_TERM = (
    '("quantitative trader" OR "quant trader" OR "algorithmic trader" OR "algo trader")'
)
_RISK_TERM = (
    '("quantitative risk analyst" OR "quant risk analyst" OR "risk quant" '
    'OR "market risk quant" OR "quant risk") -developer'
)
# ── Query list ────────────────────────────────────────────────────────────────
# Each tuple: (search_term, location, country_indeed)
# 3 role clusters × 12 cities = 36 queries per run.
QUERIES: list[tuple[str, str, str]] = []

for _term in (_RESEARCHER_TERM, _TRADER_TERM, _RISK_TERM):
    for _loc, _country in _ALL_CITIES:
        QUERIES.append((_term, _loc, _country))

SOURCE_MAP = {
    "linkedin": "LinkedIn",
    "indeed":   "Indeed",
}

# ── Early-career filter ───────────────────────────────────────────────────────
# Hard-exclude if ANY of these appear in the job title (case-insensitive).
# We don't filter by "must have new grad signal" because many quant firms post
# entry-level roles without explicit labels (e.g. "Quantitative Researcher" at
# Citadel/Two Sigma/Jane Street for new PhD/MSc grads).
SENIOR_TITLE_PATTERNS: list[str] = [
    "senior", r"\bsr\b", "lead ", "principal", "director",
    r"\bvp\b", "vice president", "head of", "managing director",
    r"\bmd\b", "manager", "staff quant", "chief ", "partner",
]
_SENIOR_RE = re.compile(
    "|".join(SENIOR_TITLE_PATTERNS), flags=re.IGNORECASE
)

# If title has no seniority signal, still check description for graduation-year
# signals that confirm the role is open to upcoming grads (2026/2027 cohort).
GRAD_SIGNALS: list[str] = [
    "new grad", "new graduate", "entry level", "entry-level",
    "early career", "early-career", "junior", "associate",
    "recent graduate", "newly graduated",
    "graduating 2026", "graduating 2027",
    "class of 2026", "class of 2027",
    "0-2 year", "0 to 2 year",
    "no prior experience", "no experience required",
    # graduation windows the user mentioned
    "december 2026", "may 2027", "spring 2027", "winter 2026",
]
_GRAD_RE = re.compile("|".join(re.escape(s) for s in GRAD_SIGNALS), flags=re.IGNORECASE)

# Title relevance gate: must contain at least one quant-finance keyword.
# Catches totally unrelated roles (nonprofit specialists, BDMs, etc.) that
# slipped through because "quantitative" appeared somewhere in the description.
_QUANT_TITLE_RE = re.compile(
    r'\bquant\b|quantitative|\balgo\b|algorithmic|\btrader\b|researcher|strategist|risk\s+analyst',
    flags=re.IGNORECASE,
)

# Companies known to post AI data-annotation gigs under quant-sounding titles.
# Recruitment agencies are NOT blocked — they may be posting real finance roles.
COMPANY_BLOCKLIST: frozenset[str] = frozenset({
    "dataannotation",
    "outlier",
    "scale ai",
    "appen",
    "remotasks",
    "telus international",
    "lionbridge",
})

# Extracts experience-requirement phrases for display in the "Exp. Req" Notion column.
# Broader than the old binary filter — captures any X-year phrase (0–99).
# The user reviews the extracted text and decides whether to apply.
_EXP_EXTRACT_RE = re.compile(
    r'(?:'
    r'\b(?:[0-9]|[1-9][0-9])\+?\s*(?:[-–]\s*\d+\s*)?years?[^.;\n]{0,60}?experience'
    r'|minimum\s+(?:of\s+)?(?:[0-9]|[1-9][0-9])\+?\s+years?[^.;\n]{0,40}'
    r'|at\s+least\s+(?:[0-9]|[1-9][0-9])\+?\s+years?[^.;\n]{0,40}'
    r')',
    flags=re.IGNORECASE
)


def extract_exp_req(desc: str) -> str:
    """Extract all experience-requirement phrases from a description.

    Returns a ' | '-joined string of unique matches, capped at 500 chars.
    Returns '' if no matches found.
    """
    if not desc:
        return ""
    matches = _EXP_EXTRACT_RE.findall(desc)
    if not matches:
        return ""
    seen: set[str] = set()
    unique: list[str] = []
    for m in matches:
        key = m.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(m.strip())
    return " | ".join(unique)[:500]


def filter_reason(row: pd.Series) -> tuple[bool, str]:
    """Returns (passed, reason). Used by test_run.py for verbose output."""
    title   = str(row.get("title",   ""))
    desc    = str(row.get("description", ""))
    company = str(row.get("company", ""))

    # Relevance gate: title must contain a quant-finance keyword
    if not _QUANT_TITLE_RE.search(title):
        return False, "EXCLUDED — no quant signal in title"

    # Company blocklist (annotation/gig platforms, not recruitment agencies)
    company_norm = _norm(company)
    if any(blocked in company_norm for blocked in COMPANY_BLOCKLIST):
        return False, f"EXCLUDED — company blocklist: '{company}'"

    # Hard exclude clearly senior/experienced titles
    senior_hit = _SENIOR_RE.search(title)
    if senior_hit:
        return False, f"EXCLUDED — senior signal in title: '{senior_hit.group()}'"

    grad_in_title = _GRAD_RE.search(title)
    if grad_in_title:
        return True, f"PASSED  — early-career signal in title: '{grad_in_title.group()}'"

    grad_in_desc = _GRAD_RE.search(desc)
    if grad_in_desc:
        return True, f"PASSED  — early-career signal in description: '{grad_in_desc.group()}'"

    return True, "PASSED  — no seniority signal (unlabelled new-grad role, kept for review)"


def is_early_career(row: pd.Series) -> bool:
    return filter_reason(row)[0]


# ── Deduplication helpers ─────────────────────────────────────────────────────
# Dedup key = normalize(role) | normalize(company) | normalize(city)
# This catches the same job posted across LinkedIn, Indeed, Glassdoor with
# different URLs but identical role+company+city.

_COMPANY_SUFFIXES = re.compile(
    r"\b(llc|inc|ltd|corp|co|group|holdings|plc|gmbh|ag|sa|nv|bv|pte|pvt|lp|llp)\b\.?",
    flags=re.IGNORECASE,
)
_PUNCT = re.compile(r"[^a-z0-9\s]")
_WS    = re.compile(r"\s+")


def _norm(text: str) -> str:
    t = text.lower().strip()
    t = _COMPANY_SUFFIXES.sub(" ", t)
    t = _PUNCT.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t


def make_dedup_key(role: str, company: str, location: str) -> str:
    city = (location or "").split(",")[0]
    return f"{_norm(role)}|{_norm(company)}|{_norm(city)}"


# ── Notion helpers ─────────────────────────────────────────────────────────────

def _text_from_prop(prop: dict, prop_type: str) -> str:
    """Safely extract plain text from a Notion property dict."""
    try:
        items = prop.get(prop_type, [])
        return " ".join(item.get("plain_text", "") for item in items)
    except Exception:
        return ""


def get_existing_keys() -> set[str]:
    """
    Return a set of normalized dedup keys for all entries already in Notion.
    Keys are built from (Role title, Company, Location) — not URL.
    """
    existing: set[str] = set()
    cursor = None
    while True:
        payload: dict = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            role     = _text_from_prop(props.get("Role",     {}), "title")
            company  = _text_from_prop(props.get("Company",  {}), "rich_text")
            location = _text_from_prop(props.get("Location", {}), "rich_text")
            key = make_dedup_key(role, company, location)
            if key:
                existing.add(key)
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return existing


def push_job(row: pd.Series) -> bool:
    """Insert a single job row into Notion. Returns True on success."""
    source   = SOURCE_MAP.get(str(row.get("site", "")).lower(), "Other")
    title    = str(row.get("title",    "Unknown Role"))[:2000]
    company  = str(row.get("company",  ""))[:2000]
    location = str(row.get("location", ""))[:2000]
    url      = str(row.get("job_url",  "")) or None

    salary = ""
    try:
        if pd.notna(row.get("min_amount")) and pd.notna(row.get("max_amount")):
            salary = f"${int(row['min_amount']):,} – ${int(row['max_amount']):,}"
        elif pd.notna(row.get("min_amount")):
            salary = f"${int(row['min_amount']):,}+"
        elif pd.notna(row.get("max_amount")):
            salary = f"Up to ${int(row['max_amount']):,}"
    except (ValueError, TypeError):
        pass

    exp_req = extract_exp_req(str(row.get("description", "")))

    payload: dict = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Role":     {"title":     [{"text": {"content": title}}]},
            "Company":  {"rich_text": [{"text": {"content": company}}]},
            "Location": {"rich_text": [{"text": {"content": location}}]},
            "Source":   {"select": {"name": source}},
            "Status":   {"select": {"name": "To Apply"}},
        },
    }
    if url:
        payload["properties"]["Apply Link"] = {"url": url}
    if salary:
        payload["properties"]["Salary Range"] = {
            "rich_text": [{"text": {"content": salary}}]
        }
    if exp_req:
        payload["properties"]["Exp. Req"] = {
            "rich_text": [{"text": {"content": exp_req}}]
        }

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS,
        json=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"    ✗ Failed ({resp.status_code}): {title} @ {company} — {resp.text[:120]}")
        return False
    return True


# ── Scraping ───────────────────────────────────────────────────────────────────

def scrape_all() -> pd.DataFrame:
    """Run all queries and return a deduplicated DataFrame of jobs."""
    frames: list[pd.DataFrame] = []

    for search_term, location, country in QUERIES:
        try:
            jobs = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=search_term,
                location=location,
                results_wanted=50,
                hours_old=48,
                job_type="fulltime",
                country_indeed=country,
                linkedin_fetch_description=False,
                verbose=0,
            )
            if not jobs.empty:
                frames.append(jobs)
                print(f"  {len(jobs):>3} results — {search_term[:60]!r} @ {location}")
            else:
                print(f"    0 results — {search_term[:60]!r} @ {location}")
        except Exception as exc:
            print(f"  ERROR — {search_term[:60]!r} @ {location}: {exc}")

        time.sleep(2)  # avoid triggering LinkedIn rate-limits between queries

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)

    # Within-run dedup by normalized key (catches cross-board duplicates)
    combined["_dedup_key"] = combined.apply(
        lambda r: make_dedup_key(
            str(r.get("title", "")),
            str(r.get("company", "")),
            str(r.get("location", "")),
        ),
        axis=1,
    )
    combined = combined.drop_duplicates(subset=["_dedup_key"])
    print(f"\n  {before} total → {len(combined)} after within-run dedup")

    # Secondary dedup: same (title, company) across different locations → keep first.
    # Catches the pattern of one job posted across many US states.
    combined["_title_co_key"] = combined.apply(
        lambda r: f"{_norm(str(r.get('title', '')))}|{_norm(str(r.get('company', '')))}",
        axis=1,
    )
    before_tc = len(combined)
    combined = combined.drop_duplicates(subset=["_title_co_key"])
    print(f"  {before_tc - len(combined)} removed by title+company dedup → {len(combined)} remain")

    # Early-career filter
    combined = combined[combined.apply(is_early_career, axis=1)].copy()
    print(f"  {len(combined)} remain after early-career filter")

    return combined


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if not NOTION_TOKEN or not NOTION_DB_ID:
        raise EnvironmentError("NOTION_TOKEN and NOTION_DB_ID env vars must be set")

    print(f"\n{'='*60}")
    print(f"Job scrape run  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    print("1/3  Fetching existing Notion entries for dedup...")
    existing_keys = get_existing_keys()
    print(f"     {len(existing_keys)} existing entries\n")

    print("2/3  Scraping & filtering job boards...")
    jobs_df = scrape_all()

    if jobs_df.empty:
        print("\nNothing passed the filters. Exiting.")
        return

    print(f"\n3/3  Pushing net-new jobs to Notion...")
    added   = 0
    skipped = 0
    for _, row in jobs_df.iterrows():
        key = row["_dedup_key"]
        if key in existing_keys:
            skipped += 1
            continue
        if push_job(row):
            added += 1
            existing_keys.add(key)

    print(f"\n{'='*60}")
    print(f"Done. {added} new jobs added  |  {skipped} already in Notion")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
