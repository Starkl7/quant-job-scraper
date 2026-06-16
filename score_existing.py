"""
score_existing.py — Back-fill Fit Score-Dhrubo / Best Resume-Dhrubo / AI Notes-Dhrubo for all existing
Notion listings that have not yet been scored.

NOT FOR GITHUB ACTIONS — run locally only. Runtime: 10–55 min depending on mode.

Fetches every page where Fit Score-Dhrubo is empty, scores them in batches of 10 using
the same Gemini pipeline as the live scrapers, then PATCHes each page in place.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODES  (toggle FETCH_MISSING_DESCRIPTIONS below)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  True  — Gemma fetches descriptions for jobs that have none.
           Higher quality scores. Runtime ~40–55 min for 458 jobs.
           Uses Gemma 4 31B quota (1,500 RPD, 15 RPM).

  False — Score on whatever description is already in Notion.
           Fast: ~8–12 min for 458 jobs.  No-description jobs get
           low_confidence=True and a note in AI Notes-Dhrubo.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run: python score_existing.py
"""

import time
import requests
from itertools import islice
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from config import (
    NOTION_TOKEN, NOTION_DB_ID, NOTION_API_VERSION,
    GEMINI_API_KEY, RESUME_FOLDER_ID, SCORING_BATCH_SIZE,
)
from scoring import (
    init_clients, load_resumes, batch_score, score_single,
    fetch_description, validate_models, ScoreResult,
)
from notion import validate_db

# ── Toggle here ────────────────────────────────────────────────────────────────
FETCH_MISSING_DESCRIPTIONS = True   # False = fast run (~10 min), True = full quality (~50 min)
# ──────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Content-Type":   "application/json",
    "Notion-Version": NOTION_API_VERSION,
}


# ── Notion helpers ─────────────────────────────────────────────────────────────

def _title_text(prop: dict) -> str:
    return "".join(t.get("plain_text", "") for t in prop.get("title", []))

def _rich_text(prop: dict) -> str:
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))

def _select_name(prop: dict) -> str:
    sel = prop.get("select")
    return sel.get("name", "") if sel else ""


# ── Fetch unscored pages ───────────────────────────────────────────────────────

def fetch_all_unscored() -> list[dict]:
    """
    Query Notion for every page where Fit Score is empty.
    Returns a list of dicts with page_id + the fields needed for scoring.
    """
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    payload: dict = {
        "page_size": 100,
        "filter": {"property": "Fit Score-Dhrubo", "number": {"is_empty": True}},
    }
    jobs: list[dict] = []

    while True:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Notion query failed ({resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            jobs.append({
                "page_id":     page["id"],
                "title":       _title_text(props.get("Role",        {})),
                "company":     _rich_text( props.get("Company",     {})),
                "location":    _rich_text( props.get("Location",    {})),
                "description": _rich_text( props.get("Description", {})),
                "site":        _select_name(props.get("Source",     {})),
            })
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    return jobs


# ── Patch score + description back to Notion ──────────────────────────────────

def patch_score(page_id: str, score: ScoreResult, description: str = "") -> bool:
    """
    PATCH scoring fields + optionally Description onto an existing page.
    Leaves all other fields (Role, Company, Status, etc.) untouched.
    Retries up to 2 times on transient errors.
    """
    parts = []
    if score.strengths:
        parts.append(f"Strengths: {score.strengths}")
    if score.weaknesses:
        parts.append(f"Weaknesses: {score.weaknesses}")
    if score.low_confidence:
        parts.append("⚠ Scored on title/company only — no description available")
    ai_notes = "\n".join(parts)

    payload: dict = {
        "properties": {
            "Fit Score-Dhrubo":   {"number": int(score.fit_score)},
            "Best Resume-Dhrubo": {"select": {"name": score.best_resume}},
            "AI Notes-Dhrubo":    {"rich_text": [{"text": {"content": ai_notes[:2000]}}]},
        }
    }
    if description:
        payload["properties"]["Description"] = {
            "rich_text": [{"text": {"content": description[:2000]}}]
        }

    for attempt in range(3):
        resp = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS, json=payload, timeout=30,
        )
        if resp.status_code == 200:
            return True
        if attempt < 2:
            time.sleep(3)

    print(f"    ✗ PATCH failed ({resp.status_code}): {resp.text[:120]}")
    return False


# ── Orchestration ──────────────────────────────────────────────────────────────

def _chunked(iterable, n):
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


def main() -> None:
    if not NOTION_TOKEN or not NOTION_DB_ID:
        raise SystemExit("NOTION_TOKEN and NOTION_DB_ID must be set in .env")
    if not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY must be set in .env")

    mode = "FULL (Gemma fetch)" if FETCH_MISSING_DESCRIPTIONS else "FAST (title+company only)"
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"\n{'='*64}")
    print(f"score_existing.py — backfill Fit Scores-Dhrubo   {ts}")
    print(f"Mode: {mode}")
    print(f"{'='*64}\n")

    # ── Startup checks ────────────────────────────────────────────────────────
    print("Startup checks…")
    validate_db()
    client, backup = init_clients()
    if backup:
        print("  ✓ Backup Gemini key available")
    validate_models(client, backup)
    print()

    # ── Fetch unscored pages ──────────────────────────────────────────────────
    print("1/3  Fetching unscored Notion pages…")
    jobs  = fetch_all_unscored()
    total = len(jobs)
    n_with_desc    = sum(1 for j in jobs if j["description"].strip())
    n_without_desc = total - n_with_desc
    print(f"     {total} unscored  ({n_with_desc} have descriptions, {n_without_desc} do not)\n")

    if not jobs:
        print("Nothing to score. Exiting.")
        return

    est_gemma   = n_without_desc * 6 if FETCH_MISSING_DESCRIPTIONS else 0
    est_gemini  = (total // SCORING_BATCH_SIZE + 1) * 6
    est_min     = round((est_gemma + est_gemini) / 60) + 2
    print(f"     Estimated runtime: ~{est_min} min\n")

    # ── Load resumes ──────────────────────────────────────────────────────────
    print("2/3  Loading resumes from Drive…")
    resumes = load_resumes()
    print()

    # ── Score + patch in batches ──────────────────────────────────────────────
    print("3/3  Scoring and updating Notion…\n")

    done            = 0
    updated         = 0
    failed          = 0
    low_conf_queue  = []     # (job, page_id) that got no description on first pass
    t_start         = time.time()

    for batch_num, batch in enumerate(_chunked(jobs, SCORING_BATCH_SIZE), 1):
        n_batch = len(batch)
        print(f"  ── Batch {batch_num}  [{done+1}–{done+n_batch} / {total}] ──")

        scores = batch_score(
            batch, resumes, client,
            fetch_missing=FETCH_MISSING_DESCRIPTIONS,
            backup_client=backup,
        )

        for job, score in zip(batch, scores):
            done += 1
            role    = job["title"][:42]
            company = job["company"][:22]
            desc    = job.get("description", "")

            if score is None:
                print(f"    [{done:>3}/{total}] ✗ parse fail — {role} @ {company}")
                failed += 1
                continue

            ok = patch_score(job["page_id"], score, description=desc)
            if ok:
                conf_tag = " ⚠low-conf" if score.low_confidence else ""
                print(f"    [{done:>3}/{total}] {score.fit_score:>2}/10  {score.best_resume:<5}{conf_tag}  {role} @ {company}")
                updated += 1
                if (score.low_confidence
                        and job.get("_was_no_desc") and not job.get("_fetched_chars")):
                    low_conf_queue.append((job, job["page_id"]))
            else:
                failed += 1
            time.sleep(0.35)

        if done < total:
            elapsed = time.time() - t_start
            rate    = done / elapsed * 60
            eta_min = (total - done) / max(rate, 0.1) / 60
            print(f"     (5s pause — {rate:.0f} jobs/min, ETA ≈ {eta_min:.0f} min)\n")
            time.sleep(5)

    # ── Retry passes: up to 2 more Gemma attempts for jobs with no description ─
    re_scored        = 0
    still_needs_desc = list(low_conf_queue) if FETCH_MISSING_DESCRIPTIONS else []
    for retry_num in range(1, 3):
        if not still_needs_desc:
            break
        print(f"\n  ↺ Retry {retry_num}/2: {len(still_needs_desc)} job(s) still missing descriptions…")
        next_round = []
        for job, page_id in still_needs_desc:
            time.sleep(5)
            fetched = fetch_description(
                client, job.get("title",""), job.get("company",""),
                job.get("location",""), backup_client=backup,
            )
            if not fetched:
                print(f"    → still no description: {job.get('title','')[:40]}")
                next_round.append((job, page_id))
                continue
            job["description"]    = fetched
            job["_fetched_chars"] = len(fetched)
            new_score = score_single(job, resumes, client, backup_client=backup)
            if new_score:
                new_score.low_confidence = False
                if patch_score(page_id, new_score, description=fetched):
                    re_scored += 1
                    print(f"    ✓ re-scored {new_score.fit_score}/10 — {job.get('title','')[:40]}")
        still_needs_desc = next_round

    elapsed_total = (time.time() - t_start) / 60
    print(f"\n{'='*64}")
    print(f"Done.  {updated} scored  |  {failed} failed  |  {re_scored} re-scored  |  {elapsed_total:.1f} min total")
    print(f"{'='*64}\n")


if __name__ == "__main__":
    main()
