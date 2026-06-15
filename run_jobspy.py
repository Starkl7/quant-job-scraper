"""
run_jobspy.py — LinkedIn + Indeed pipeline entry point.

Phase 1: Scrape (JobSpy) → Filter → Dedup against Notion
Phase 2: Batch score (Gemini, 10 jobs/call) → Push to Notion
Phase 3: Retry low-confidence jobs (once) → PATCH Notion
Phase 4: Slack summary

Schedule: every 6 hours via GitHub Actions (scrape.yml).
Run locally: python run_jobspy.py
"""

from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import notion
from config import NOTION_TOKEN, NOTION_DB_ID, GEMINI_API_KEY
from candidates import get_configured_candidates, load_all_resumes
from filters import apply_filters
from notify import send_slack
from pipeline import retry_low_confidence_jobs, score_and_push_jobs
from scoring import init_clients, validate_models
from scrapers.jobspy import scrape_all


def main() -> None:
    if not NOTION_TOKEN or not NOTION_DB_ID:
        raise SystemExit("NOTION_TOKEN and NOTION_DB_ID must be set in environment")
    if not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY must be set in environment")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*60}")
    print(f"JobSpy run — LinkedIn + Indeed    {ts}")
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

    candidates = get_configured_candidates()
    print(f"  Active candidates: {', '.join(c.display_name for c in candidates)}")
    resumes_by_candidate = load_all_resumes(candidates)
    print()

    # ── Phase 1: Scrape, filter, dedup ────────────────────────────────────────
    print("1/3  Fetching existing Notion keys for dedup…")
    existing_keys = notion.get_existing_keys()
    print(f"     {len(existing_keys)} existing entries\n")

    print("2/3  Scraping LinkedIn + Indeed…")
    raw_df = scrape_all()

    if raw_df.empty:
        msg = f"🤖 *JobSpy* ({ts}) — scraper returned 0 results."
        print(f"\n{msg}")
        send_slack(msg)
        return

    filtered_df = apply_filters(raw_df)

    if filtered_df.empty:
        msg = f"🤖 *JobSpy* ({ts}) — 0 jobs passed filters."
        print(f"\n{msg}")
        send_slack(msg)
        return

    net_new = filtered_df[~filtered_df["_dedup_key"].isin(existing_keys)]
    print(f"  {len(net_new)} net-new (not yet in Notion)\n")

    if net_new.empty:
        msg = f"🤖 *JobSpy* ({ts}) — all jobs already in Notion (0 net-new)."
        print(msg)
        send_slack(msg)
        return

    # ── Phase 2: Score + push ─────────────────────────────────────────────────
    print("3/3  Scoring and pushing to Notion…\n")

    jobs_list = net_new.to_dict("records")
    added, failed_push, low_conf_queue, source_counts = score_and_push_jobs(
        jobs_list, client, backup, resumes_by_candidate, candidates,
    )

    # ── Phase 3: Low-confidence retries ───────────────────────────────────────
    re_scored = retry_low_confidence_jobs(
        low_conf_queue, client, backup, resumes_by_candidate, candidates,
    )

    # ── Log failed pushes ──────────────────────────────────────────────────────
    if failed_push:
        print(f"\n  ✗ {len(failed_push)} job(s) failed to push to Notion:")
        for job, _ in failed_push:
            print(f"    • {job.get('title', '')[:50]} @ {job.get('company', '')[:25]}")

    # ── Phase 4: Slack summary ────────────────────────────────────────────────
    src_str = "  ".join(f"{k}:{v}" for k, v in sorted(source_counts.items()))
    lines = [
        f"🤖 *JobSpy (LinkedIn + Indeed)* — {ts}",
        f"✅ {added} added  |  ❌ {len(failed_push)} failed  |  🔄 {re_scored}/{len(low_conf_queue)} re-scored after retry",
        f"📌 Sources: {src_str or 'none'}",
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
