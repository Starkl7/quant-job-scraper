"""
Dry-run test — scrapes ~10 real job listings (LinkedIn + Indeed) and shows
exactly which pass or fail the dedup + early-career filter, and why.

No NOTION_TOKEN or NOTION_DB_ID required.
Run:  python test_run.py
"""

import sys

import pandas as pd
from jobspy import scrape_jobs

from scrape import _RESEARCHER_TERM, _TRADER_TERM, _RISK_TERM
from scrape import extract_exp_req, filter_reason, make_dedup_key

# ── Scrape a small real sample ────────────────────────────────────────────────
# One US city + one intl city, all 3 role clusters — mirrors production queries
# without touching Notion (no secrets needed).

TEST_CITIES = [
    ("New York, NY",           "USA"),
    ("London, United Kingdom", "UK"),
]

print("\n" + "=" * 70)
print("DRY-RUN TEST  —  LinkedIn + Indeed")
print(f"Cities: {', '.join(c for c, _ in TEST_CITIES)}  |  results_wanted: 10 per query")
print("=" * 70 + "\n")

frames = []

for loc, country in TEST_CITIES:
    for term in (_RESEARCHER_TERM, _TRADER_TERM, _RISK_TERM):
        try:
            batch = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=term,
                location=loc,
                results_wanted=10,
                hours_old=48,
                job_type="fulltime",
                country_indeed=country,
                linkedin_fetch_description=False,
                verbose=0,
            )
            print(f"  {len(batch):>3} raw — {term[:55]!r} @ {loc}")
            if not batch.empty:
                frames.append(batch)
        except Exception as exc:
            print(f"  ERROR — {term[:55]!r} @ {loc}: {exc}")

if not frames:
    print("\nNo jobs returned from any source.")
    sys.exit(0)

jobs = pd.concat(frames, ignore_index=True)
print(f"\nRaw results: {len(jobs)} listings\n")

# ── Apply dedup ───────────────────────────────────────────────────────────────

jobs["_dedup_key"] = jobs.apply(
    lambda r: make_dedup_key(
        str(r.get("title", "")),
        str(r.get("company", "")),
        str(r.get("location", "")),
    ),
    axis=1,
)

before_dedup = len(jobs)
jobs = jobs.drop_duplicates(subset=["_dedup_key"])
dedup_removed = before_dedup - len(jobs)

print(f"After within-run dedup (role+company+city): {len(jobs)} remain  ({dedup_removed} duplicates removed)\n")

# ── Apply early-career filter and report ─────────────────────────────────────

print("-" * 70)
print(f"{'#':<4} {'TITLE':<42} {'COMPANY':<22} VERDICT")
print("-" * 70)

passed = 0
excluded = 0

for i, (_, row) in enumerate(jobs.iterrows(), 1):
    title   = str(row.get("title",   ""))
    company = str(row.get("company", ""))
    ok, reason = filter_reason(row)

    title_display   = (title[:40]   + "..") if len(title)   > 42 else title
    company_display = (company[:20] + "..") if len(company) > 22 else company

    verdict_short = "✓ PASS" if ok else "✗ FAIL"
    print(f"{i:<4} {title_display:<42} {company_display:<22} {verdict_short}")
    print(f"     └─ {reason}")
    exp_req = extract_exp_req(str(row.get("description", "")))
    if exp_req:
        display_req = (exp_req[:80] + "..") if len(exp_req) > 82 else exp_req
        print(f"     └─ Exp. Req : {display_req}")
    if ok:
        passed += 1
    else:
        excluded += 1

print("-" * 70)
print(f"\nSummary: {passed} would be pushed to Notion  |  {excluded} excluded\n")

# ── Show full details for passed jobs ─────────────────────────────────────────

passed_jobs = jobs[jobs.apply(lambda r: filter_reason(r)[0], axis=1)]

if not passed_jobs.empty:
    print("=" * 70)
    print("DETAIL — jobs that would be pushed to Notion:")
    print("=" * 70)
    for _, row in passed_jobs.iterrows():
        print(f"\n  Title   : {row.get('title', '')}")
        print(f"  Company : {row.get('company', '')}")
        print(f"  Location: {row.get('location', '')}")
        print(f"  Site    : {row.get('site', '')}")
        print(f"  URL     : {row.get('job_url', '')}")
        salary = ""
        try:
            if pd.notna(row.get("min_amount")) and pd.notna(row.get("max_amount")):
                salary = f"${int(row['min_amount']):,} – ${int(row['max_amount']):,}"
        except Exception:
            pass
        if salary:
            print(f"  Salary  : {salary}")
