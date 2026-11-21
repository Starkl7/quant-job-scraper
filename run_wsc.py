"""
run_wsc.py — wallstreetcareers.com pipeline entry point.

Keyword-search driven (like LinkedIn), so it gets the normal quant filters but not the
ATS "explicit early-career label" rule. The site syncs employer feeds in a daily burst
around 15-16 UTC, so this runs twice a day: shortly after the burst and once overnight.

Phase 1: scrape → filter → dedup against Notion
Phase 2: batch score (Gemini) with real posting text (JSON-LD) → push to Notion
Phase 3: Slack summary + run-health log

Run locally: python run_wsc.py
"""

import re
import time
from datetime import datetime, timezone
from itertools import islice

from dotenv import load_dotenv
load_dotenv()

import notion
from config import NOTION_TOKEN, NOTION_DB_ID, GEMINI_API_KEY, SCORING_BATCH_SIZE
from filters import apply_filters, is_known_job, make_index_keys
from notify import send_slack
from runlog import RunLog
from scoring import init_clients, load_resumes, batch_score, validate_models
from scrapers.wsc import scrape_wsc

_EXPERIENCED_RE = re.compile(r"\bexperienced\b", re.IGNORECASE)
_INTERN_RE      = re.compile(r"\bintern\b|\binternship\b|working\s+student", re.IGNORECASE)


def _chunked(iterable, n):
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


def _with_flags(msg: str, runlog: RunLog) -> str:
    flags = runlog.slack_flags_line()
    return msg + (f"\n{flags}" if flags else "")


def _main(runlog: RunLog) -> None:
    if not NOTION_TOKEN or not NOTION_DB_ID:
        raise SystemExit("NOTION_TOKEN and NOTION_DB_ID must be set in environment")
    if not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY must be set in environment")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*60}\nWallStreetCareers run    {ts}\n{'='*60}\n")

    print("Startup checks…")
    notion.validate_db()
    client, backup = init_clients()
    validate_models(client, backup)
    resumes = load_resumes()
    print()

    print("1/3  Fetching existing Notion keys for dedup…")
    existing_keys = notion.get_existing_keys()
    print(f"     {len(existing_keys)} existing dedup keys\n")

    print("2/3  Scraping wallstreetcareers.com…")
    with runlog.phase("scrape"):
        raw_df = scrape_wsc(runlog=runlog)
    runlog.funnel["raw"] = len(raw_df)
    if raw_df.empty:
        msg = _with_flags(f"💼 *WallStreetCareers* ({ts}) — scraper returned 0 results.", runlog)
        print(msg); send_slack(msg)
        return

    filtered = apply_filters(raw_df)
    bad = filtered["title"].apply(lambda t: bool(_EXPERIENCED_RE.search(str(t)))
                                  or bool(_INTERN_RE.search(str(t))))
    filtered = filtered[~bad].copy()
    runlog.funnel["after_filters"] = len(filtered)
    runlog.dropped_titles = list(filtered.attrs.get("dropped_titles", []))

    net_new = filtered[~filtered.apply(
        lambda r: is_known_job(str(r.get("title", "")), str(r.get("company", "")),
                               str(r.get("location", "")), existing_keys),
        axis=1,
    )] if not filtered.empty else filtered
    runlog.funnel["net_new"] = len(net_new)
    print(f"     {len(filtered)} passed filters, {len(net_new)} net-new\n")

    if net_new.empty:
        msg = _with_flags(f"💼 *WallStreetCareers* ({ts}) — 0 net-new jobs "
                          f"({len(filtered)} matched filters).", runlog)
        print(msg); send_slack(msg)
        return

    print(f"3/3  Scoring and pushing {len(net_new)} jobs to Notion…\n")
    added = visa_dropped = 0
    failed_push: list = []
    low_conf = 0
    jobs = net_new.to_dict("records")
    t0 = time.time()

    for batch in _chunked(jobs, SCORING_BATCH_SIZE):
        scores = batch_score(batch, resumes, client, fetch_missing=True, backup_client=backup)
        for job, score in zip(batch, scores):
            if score and score.visa_sponsored is False:
                print(f"    ✗ no visa — {job.get('title','')[:40]} @ {job.get('company','')[:20]}")
                visa_dropped += 1
                continue
            page_id = notion.push_job(job, score)
            if page_id:
                added += 1
                low_conf += int(bool(score and score.low_confidence))
                existing_keys.update(make_index_keys(
                    str(job.get("title", "")), str(job.get("company", "")),
                    str(job.get("location", ""))))
                print(f"    ✓ {job.get('title','')[:40]} @ {job.get('company','')[:20]}")
            else:
                failed_push.append((job, score))
            time.sleep(0.35)
        time.sleep(5)
    runlog.phases["scoring"] = round(time.time() - t0, 1)

    runlog.counts.update(added=added, failed_push=len(failed_push),
                         visa_dropped=visa_dropped, low_confidence=low_conf)
    lines = [
        f"💼 *WallStreetCareers* — {ts}",
        f"✅ {added} added  |  ❌ {len(failed_push)} failed  |  🚫 {visa_dropped} visa-denied  "
        f"|  ⚠ {low_conf} low-confidence",
    ]
    if failed_push:
        lines.append("⚠️ Failed pushes: " + ", ".join(
            f"{j.get('title','?')[:30]} @ {j.get('company','?')[:15]}" for j, _ in failed_push[:3]))
    msg = _with_flags("\n".join(lines), runlog)
    print(f"\n{msg}")
    send_slack(msg)


def main() -> None:
    runlog = RunLog("wsc")
    try:
        _main(runlog)
    finally:
        runlog.write()


if __name__ == "__main__":
    main()
