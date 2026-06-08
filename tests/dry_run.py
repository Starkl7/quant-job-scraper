"""
tests/dry_run.py — Smoke test for both scrapers.

Scrapes a small sample, runs through all filters, and prints a detailed
pass/fail report. No Notion writes, no LLM calls, no API keys required
beyond SERPAPI_KEY_1 / SERPAPI_KEY_2 for the Google Jobs test.

Run:  python tests/dry_run.py [jobspy|serpapi|both]  (default: both)
"""

import sys
import os

# Allow running from project root or from tests/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from filters import apply_filters, filter_reason, extract_exp_req

SEP = "=" * 70


# ── JobSpy dry run ─────────────────────────────────────────────────────────────

def run_jobspy_test():
    from scrapers.jobspy import scrape_one
    from config import RESEARCHER_TERM

    print(f"\n{SEP}")
    print("DRY RUN — JobSpy (LinkedIn + Indeed)")
    print(f"Term: Researcher  |  Location: New York, NY  |  results_wanted: 10")
    print(f"{SEP}\n")

    try:
        df = scrape_one(
            search_term    = RESEARCHER_TERM,
            location       = "New York, NY",
            country        = "USA",
            results_wanted = 10,
            hours_old      = 168,   # 1 week for test — wider window ensures results
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return

    print(f"Raw results: {len(df)}\n")
    _print_filter_report(df, "JobSpy")


# ── SerpAPI dry run ────────────────────────────────────────────────────────────

def run_serpapi_test():
    from scrapers.serpapi import scrape_one, to_dataframe
    from config import GJ_TERMS, SERPAPI_KEY_GROUPS

    print(f"\n{SEP}")
    print("DRY RUN — SerpAPI (Google Jobs)")
    print(f"Term: Researcher + ModelRisk  |  NYC  |  date_posted:today")
    print(f"{SEP}\n")

    api_key = os.getenv("SERPAPI_KEY_1")
    if not api_key:
        print("SERPAPI_KEY_1 not set — skipping SerpAPI test")
        return

    frames = []
    for label in ("Researcher", "ModelRisk"):
        try:
            raw = scrape_one(GJ_TERMS[label], "New York, NY", api_key)
            df  = to_dataframe(raw)
            print(f"  {len(raw):>3} results — {label}")
            frames.append(df)
        except Exception as exc:
            print(f"  ERROR — {label}: {exc}")

    if not frames:
        print("No results.")
        return

    combined = pd.concat(frames, ignore_index=True)
    print(f"\nRaw: {len(combined)} listings\n")
    _print_filter_report(combined, "SerpAPI")


# ── Shared filter report ───────────────────────────────────────────────────────

def _print_filter_report(df: pd.DataFrame, source: str):
    if df.empty:
        print("No data to report.")
        return

    print(f"{'─'*70}")
    print(f"  {'#':<3} {'TITLE':<42} {'COMPANY':<20} VERDICT")
    print(f"{'─'*70}")

    passed_count = excluded_count = 0

    for i, (_, row) in enumerate(df.iterrows(), 1):
        title   = str(row.get("title",   ""))
        company = str(row.get("company", ""))
        ok, reason = filter_reason(row)

        t_display = (title[:40]   + "..") if len(title)   > 42 else title
        c_display = (company[:18] + "..") if len(company) > 20 else company

        verdict = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {i:<3} {t_display:<42} {c_display:<20} {verdict}")
        print(f"       └─ {reason}")

        exp = extract_exp_req(str(row.get("description", "")))
        if exp:
            display_exp = (exp[:80] + "..") if len(exp) > 82 else exp
            print(f"       └─ Exp: {display_exp}")

        if ok:
            passed_count += 1
        else:
            excluded_count += 1

    print(f"{'─'*70}")
    print(f"\n  {source} summary: {passed_count} pass  |  {excluded_count} excluded\n")

    # Detail for passing jobs
    passing = df[df.apply(lambda r: filter_reason(r)[0], axis=1)]
    if not passing.empty:
        print(f"  Passing jobs detail:")
        for _, row in passing.iterrows():
            url = str(row.get("job_url", ""))
            salary = ""
            try:
                if pd.notna(row.get("min_amount")) and pd.notna(row.get("max_amount")):
                    salary = f"  ${int(row['min_amount']):,}–${int(row['max_amount']):,}"
            except Exception:
                pass
            desc_len = len(str(row.get("description", "")))
            print(f"    • {row.get('title','')} @ {row.get('company','')} [{row.get('site','')}]{salary}  desc={desc_len}c")
            if url and url not in ("nan", "None", ""):
                print(f"      {url[:90]}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "both"

    if mode in ("jobspy", "both"):
        run_jobspy_test()

    if mode in ("serpapi", "both"):
        run_serpapi_test()

    print(f"\n{SEP}")
    print("Dry run complete — no Notion writes were made.")
    print(f"{SEP}\n")


if __name__ == "__main__":
    main()
