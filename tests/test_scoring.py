"""
tests/test_scoring.py — In-depth scoring pipeline test.

Collects 10 real job listings (5 with descriptions, 5 with descriptions
intentionally cleared to test the fetch_description path), runs them through
the full Phase 2 pipeline, and prints a detailed analysis of:
  • Score calibration (is the model inflating?)
  • Resume selection accuracy (does QR vs QT vs QA vs Risk make sense?)
  • Specificity of strengths/weaknesses
  • fetch_description quality for no-description jobs
  • JSON parse reliability
  • Timing

Run: python tests/test_scoring.py
"""

import os
import sys
import time
import copy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from scrapers.serpapi import scrape_one, to_dataframe
from scoring import init_client, load_resumes, batch_score, ScoreResult
from config import GJ_TERMS, SCORING_MODEL

SEP  = "=" * 72
DSEP = "─" * 72

# ── Collect 10 test jobs ───────────────────────────────────────────────────────

def collect_jobs() -> list[dict]:
    """
    Scrape ~12 jobs across 4 terms from NYC.
    Return first 10 as job dicts, mixed: 5 keep descriptions, 5 have descriptions cleared.
    """
    api_key = os.getenv("SERPAPI_KEY_1")
    if not api_key:
        raise SystemExit("SERPAPI_KEY_1 not set")

    print(f"\n{SEP}")
    print("COLLECTING TEST JOBS via SerpAPI — NYC, all 4 terms")
    print(f"{SEP}\n")

    frames = []
    for label, q in GJ_TERMS.items():
        try:
            raw = scrape_one(q, "New York, NY", api_key)
            df  = to_dataframe(raw)
            df["_term_label"] = label
            frames.append(df)
            print(f"  {len(raw):>3} results — {label}")
        except Exception as exc:
            print(f"  ERROR — {label}: {exc}")
        time.sleep(2)

    import pandas as pd
    if not frames:
        raise SystemExit("No jobs collected from SerpAPI")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["title", "company"], keep="first"
    ).head(12)

    jobs = combined.to_dict("records")

    # Take first 10; clear descriptions on jobs 6-10 to test fetch_description
    jobs = jobs[:10]
    for i in range(5, 10):
        jobs[i]["_original_description"] = jobs[i].get("description", "")
        jobs[i]["description"] = ""   # simulate missing description

    print(f"\n  → {len(jobs)} jobs collected")
    print(f"    Jobs 1–5:  description KEPT (test normal path)")
    print(f"    Jobs 6–10: description CLEARED (test fetch_description path)\n")
    return jobs


# ── Run scoring ────────────────────────────────────────────────────────────────

def run_scoring(jobs: list[dict], resume_pdfs: dict, client) -> tuple[list, float]:
    print(f"{SEP}")
    print(f"SCORING — model: {SCORING_MODEL}")
    print(f"{SEP}\n")

    t0 = time.time()
    scores = batch_score(jobs, resume_pdfs, client)
    elapsed = time.time() - t0

    return scores, elapsed


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyse(jobs: list[dict], scores: list[ScoreResult | None], elapsed: float) -> None:

    print(f"\n{SEP}")
    print("DETAILED ANALYSIS — per job")
    print(f"{SEP}\n")

    parse_failures = 0
    score_values   = []
    resume_choices = {}
    vague_count    = 0
    fetch_jobs     = []

    for i, (job, score) in enumerate(zip(jobs, scores), 1):
        title    = str(job.get("title",    ""))[:55]
        company  = str(job.get("company",  ""))[:25]
        location = str(job.get("location", ""))[:20]
        term     = str(job.get("_term_label", ""))
        had_desc = i <= 5   # jobs 1-5 had description kept

        print(f"  Job {i:>2}  [{term:<12}]  {'WITH desc' if had_desc else 'NO desc  '}")
        print(f"         {title}")
        print(f"         {company} — {location}")

        if score is None:
            parse_failures += 1
            print(f"         ✗ PARSE FAILURE — no ScoreResult returned\n")
            continue

        # Score
        score_values.append(score.fit_score)
        print(f"         Fit score    : {score.fit_score}/10  {'⚠ possibly inflated' if score.fit_score >= 9 else ''}")
        print(f"         Best resume  : {score.best_resume}  {'⚠ low confidence' if score.low_confidence else ''}")

        # Resume selection check
        resume_choices[score.best_resume] = resume_choices.get(score.best_resume, 0) + 1

        # Strengths analysis
        strengths_list = [s.strip() for s in score.strengths.split("|") if s.strip()]
        print(f"         Strengths ({len(strengths_list)}):")
        for s in strengths_list:
            is_vague = len(s) < 30 or not any(
                kw in s.lower() for kw in [
                    "kalman", "es ", "futures", "forex", "fx", "vol", "psi", "roc", "ks ",
                    "python", "c++", "sas", "sql", "monte carlo", "stochastic",
                    "credit", "model", "risk", "microstructure", "quantlib", "databento",
                    "mfm", "ncsu", "wells fargo", "bloomberg", "sharpe", "stat arb",
                    "backtest", "signal", "strategy", "analytics", "validation"
                ]
            )
            marker = "  ⚠ vague" if is_vague else ""
            print(f"           • {s}{marker}")
            if is_vague:
                vague_count += 1

        # Weaknesses analysis
        weakness_list = [w.strip() for w in score.weaknesses.split("|") if w.strip()]
        print(f"         Weaknesses ({len(weakness_list)}):")
        for w in weakness_list:
            print(f"           • {w}")

        # For no-desc jobs: fetch quality
        if not had_desc:
            fetched = str(job.get("description", ""))
            orig    = str(job.get("_original_description", ""))
            fetch_quality = (
                "✓ description fetched" if len(fetched) > 200
                else "⚠ description NOT fetched — scored on title/company only"
            )
            print(f"         Fetch result : {fetch_quality} ({len(fetched)} chars)")
            fetch_jobs.append({
                "title": title, "fetched_chars": len(fetched),
                "original_chars": len(orig), "score": score.fit_score,
                "score_with": None  # filled in cross-analysis below
            })

        print()

    # ── Cross-analysis: do scores differ with vs without description? ──────────
    # For jobs that had a description and appeared twice (once with, once without)
    # we can't directly compare here, but we can note score ranges.

    print(f"{DSEP}")
    print("AGGREGATE ANALYSIS")
    print(f"{DSEP}\n")

    n_scored = len([s for s in scores if s is not None])
    print(f"  Jobs scored successfully : {n_scored}/{len(jobs)}")
    print(f"  JSON parse failures      : {parse_failures}")
    print(f"  Total elapsed time       : {elapsed:.1f}s  ({elapsed/len(jobs):.1f}s per job)")
    print()

    if score_values:
        avg = sum(score_values) / len(score_values)
        print(f"  Score distribution:")
        print(f"    Min: {min(score_values)}  Max: {max(score_values)}  Avg: {avg:.1f}")
        print(f"    {'⚠ INFLATION LIKELY — avg ≥ 7.5' if avg >= 7.5 else '✓ Calibration looks reasonable (avg < 7.5)'}")
        # Histogram
        buckets = {r: 0 for r in ["1-2", "3-4", "5-6", "7-8", "9-10"]}
        for v in score_values:
            if v <= 2:   buckets["1-2"]  += 1
            elif v <= 4: buckets["3-4"]  += 1
            elif v <= 6: buckets["5-6"]  += 1
            elif v <= 8: buckets["7-8"]  += 1
            else:        buckets["9-10"] += 1
        print(f"    Histogram: " + "  ".join(f"{k}:{v}" for k,v in buckets.items()))
    print()

    print(f"  Resume selection:")
    for label in ("QT", "QR", "QA", "Risk"):
        count = resume_choices.get(label, 0)
        bar = "█" * count
        print(f"    {label:<5} {bar} {count}")
    print()

    print(f"  Specificity:")
    total_strengths = sum(
        len([s for s in (sc.strengths if sc else "").split("|") if s.strip()])
        for sc in scores if sc
    )
    print(f"    Total strength bullets    : {total_strengths}")
    print(f"    Vague bullets flagged     : {vague_count}  "
          f"({'⚠ too many vague — prompt needs work' if vague_count > total_strengths * 0.3 else '✓ mostly specific'})")
    print()

    if fetch_jobs:
        fetched_ok  = sum(1 for j in fetch_jobs if j["fetched_chars"] > 200)
        fetched_avg = sum(j["fetched_chars"] for j in fetch_jobs) / len(fetch_jobs)
        print(f"  fetch_description results:")
        print(f"    Jobs needing fetch        : {len(fetch_jobs)}")
        print(f"    Successfully fetched      : {fetched_ok}/{len(fetch_jobs)}")
        print(f"    Avg fetched chars         : {fetched_avg:.0f}")
        print(f"    {'✓ Search path working' if fetched_ok >= 3 else '⚠ Search finding few descriptions — check rate limits'}")
    print()

    # ── Verdict ──────────────────────────────────────────────────────────────
    print(f"{DSEP}")
    print("VERDICT")
    print(f"{DSEP}\n")

    issues = []
    if parse_failures > 0:
        issues.append(f"JSON parse failures: {parse_failures} — add more explicit output format instructions")
    if score_values and sum(score_values)/len(score_values) >= 7.5:
        issues.append("Score inflation — tighten rubric or add calibration examples to prompt")
    if vague_count > total_strengths * 0.3:
        issues.append("Vague strengths — add negative examples to prompt (show what NOT to write)")
    if fetch_jobs and sum(1 for j in fetch_jobs if j["fetched_chars"] > 200) < len(fetch_jobs) // 2:
        issues.append("fetch_description failing often — check RPM limits or search query wording")

    if not issues:
        print("  ✓ All checks passed — pipeline performing as expected.\n")
    else:
        print(f"  ⚠ {len(issues)} issue(s) found:\n")
        for issue in issues:
            print(f"    • {issue}")
        print()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    jobs       = collect_jobs()
    client     = init_client()
    resume_pdfs = load_resumes()

    scores, elapsed = run_scoring(jobs, resume_pdfs, client)
    analyse(jobs, scores, elapsed)

    print(f"{SEP}")
    print("Test complete.")
    print(f"{SEP}\n")


if __name__ == "__main__":
    main()
