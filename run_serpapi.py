"""
run_serpapi.py — Google Jobs pipeline entry point.

Phase 1: Scrape (SerpAPI) → Filter → Dedup against Notion
Phase 2: Batch score (Gemini, 10 jobs/call) → Push to Notion
Phase 3: Retry low-confidence jobs (once) → PATCH Notion
Phase 4: Slack summary

Schedule: daily at 23:00 UTC via GitHub Actions (score.yml).
Run locally: python run_serpapi.py
"""

import time
from datetime import datetime, timezone
from itertools import islice

from dotenv import load_dotenv
load_dotenv()

import notion
from config import (
    NOTION_TOKEN, NOTION_DB_ID, GEMINI_API_KEY,
    SCORING_BATCH_SIZE, SERPAPI_DATE_FILTER, GJ_TERMS, SERPAPI_DRY_RUN,
)
from filters import apply_filters
from notify import send_slack
from scoring import (
    init_clients, load_resumes, batch_score,
    fetch_description, score_single, validate_models,
)
from scrapers.serpapi import scrape_all


def _chunked(iterable, n):
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


def main() -> None:
    if not NOTION_TOKEN or not NOTION_DB_ID:
        raise SystemExit("NOTION_TOKEN and NOTION_DB_ID must be set in environment")
    if not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY must be set in environment")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*60}")
    print(f"SerpAPI run — Google Jobs         {ts}")
    print(f"Filter: {SERPAPI_DATE_FILTER}  |  {len(GJ_TERMS)} terms  |  4 cities  |  2 keys")
    if SERPAPI_DRY_RUN:
        print("*** DRY RUN — no SerpAPI credits will be consumed ***")
    print(f"{'='*60}\n")

    # ── Startup checks ────────────────────────────────────────────────────────
    print("Startup checks…")
    notion.validate_db()
    client, backup = init_clients()
    if backup:
        print("  ✓ Backup Gemini key available")
    else:
        print("  ⚠ No backup Gemini key (GEMINI_API_KEY_2 not set or same project)")
    validate_models(client, backup)
    resumes = load_resumes()
    print()

    # ── Phase 1: Scrape, filter, dedup ────────────────────────────────────────
    print("1/3  Fetching existing Notion keys for dedup…")
    existing_keys = notion.get_existing_keys()
    print(f"     {len(existing_keys)} existing entries\n")

    print("2/3  Scraping Google Jobs via SerpAPI…")
    raw_df = scrape_all()

    if raw_df.empty:
        msg = f"🤖 *SerpAPI* ({ts}) — scraper returned 0 results{' (DRY RUN)' if SERPAPI_DRY_RUN else ''}."
        print(f"\n{msg}")
        send_slack(msg)
        return

    filtered_df = apply_filters(raw_df)

    if filtered_df.empty:
        msg = f"🤖 *SerpAPI* ({ts}) — 0 jobs passed filters."
        print(f"\n{msg}")
        send_slack(msg)
        return

    net_new = filtered_df[~filtered_df["_dedup_key"].isin(existing_keys)]
    print(f"  {len(net_new)} net-new (not yet in Notion)\n")

    if net_new.empty:
        msg = f"🤖 *SerpAPI* ({ts}) — all jobs already in Notion (0 net-new)."
        print(msg)
        send_slack(msg)
        return

    # ── Phase 2: Score + push ─────────────────────────────────────────────────
    print("3/3  Scoring and pushing to Notion…\n")

    added           = 0
    visa_dropped    = 0
    failed_push     = []
    low_conf_queue  = []
    jobs_list       = net_new.to_dict("records")

    for batch in _chunked(jobs_list, SCORING_BATCH_SIZE):
        scores = batch_score(batch, resumes, client,
                             fetch_missing=True, backup_client=backup)

        for job, score in zip(batch, scores):
            if score and score.visa_sponsored is False:
                print(f"    ✗ no visa sponsorship — skipping: {job.get('title','')[:40]} @ {job.get('company','')[:20]}")
                visa_dropped += 1
                continue
            page_id = notion.push_job(job, score)
            if page_id:
                added += 1
                existing_keys.add(job["_dedup_key"])
                if (score and score.low_confidence
                        and job.get("_was_no_desc") and not job.get("_fetched_chars")):
                    low_conf_queue.append((job, page_id))
            else:
                failed_push.append((job, score))
            time.sleep(0.35)

        # Gemini free tier: 15 RPM → 5s between batches
        time.sleep(5)

    # ── Phase 3: Low-confidence retries (up to 2 attempts per job) ───────────
    re_scored        = 0
    still_needs_desc = list(low_conf_queue)
    for retry_num in range(1, 3):
        if not still_needs_desc:
            break
        print(f"\n  ↺ Retry {retry_num}/2: {len(still_needs_desc)} job(s) still missing descriptions…")
        next_round = []
        for job, page_id in still_needs_desc:
            time.sleep(5)
            fetched, visa_ok = fetch_description(
                client, job.get("title", ""), job.get("company", ""),
                job.get("location", ""), backup_client=backup,
            )
            if not fetched:
                print(f"    → still no description: {job.get('title', '')[:40]}")
                next_round.append((job, page_id))
                continue
            if visa_ok is False:
                print(f"    ✗ no visa sponsorship — skipping: {job.get('title', '')[:40]}")
                visa_dropped += 1
                continue
            job["description"]    = fetched
            job["_fetched_chars"] = len(fetched)
            new_score = score_single(job, resumes, client, backup_client=backup)
            if new_score:
                if new_score.visa_sponsored is False:
                    print(f"    ✗ no visa sponsorship (re-scored) — skipping: {job.get('title', '')[:40]}")
                    visa_dropped += 1
                    continue
                new_score.low_confidence = False
                if notion.update_job_score(page_id, new_score, description=fetched):
                    re_scored += 1
                    print(f"    ✓ re-scored {new_score.fit_score}/10 — {job.get('title', '')[:40]}")
        still_needs_desc = next_round

    # ── Log failed pushes ──────────────────────────────────────────────────────
    if failed_push:
        print(f"\n  ✗ {len(failed_push)} job(s) failed to push to Notion:")
        for job, _ in failed_push:
            print(f"    • {job.get('title', '')[:50]} @ {job.get('company', '')[:25]}")

    # ── Phase 4: Slack summary ────────────────────────────────────────────────
    lines = [
        f"🤖 *SerpAPI (Google Jobs)* — {ts}",
        f"✅ {added} added  |  ❌ {len(failed_push)} failed  |  🔄 {re_scored}/{len(low_conf_queue)} re-scored after retry  |  🚫 {visa_dropped} visa-denied dropped",
    ]
    if failed_push:
        lines.append("⚠️ Failed pushes: " + ", ".join(
            f"{j.get('title', '?')[:30]} @ {j.get('company', '?')[:15]}"
            for j, _ in failed_push[:3]
        ) + ("…" if len(failed_push) > 3 else ""))
    summary = "\n".join(lines)
    print(f"\n{'='*60}\n{summary}\n{'='*60}\n")
    send_slack(summary)


if __name__ == "__main__":
    main()
