"""
run_ats.py — Direct ATS pipeline entry point.

Polls 43 company ATS endpoints (Greenhouse, Lever, Recruitee, Pinpoint, Workable)
and pushes net-new matching roles into the shared Notion job tracker.

Phase 1: Fetch from ATS endpoints → Filter → Dedup against Notion
Phase 2: Batch score (Gemini, 10 jobs/call) → Push to Notion
Phase 3: Retry low-confidence jobs → PATCH Notion
Phase 4: Slack summary

Schedule: every 4 hours via GitHub Actions (ats.yml).
Run locally: python run_ats.py
"""

import re
import time
from datetime import datetime, timezone
from itertools import islice

import pandas as pd
from dotenv import load_dotenv
load_dotenv()

import notion
from config import (
    NOTION_TOKEN, NOTION_DB_ID, GEMINI_API_KEY,
    SCORING_BATCH_SIZE,
)
from filters import apply_filters, is_known_job, make_index_keys
from notify import send_slack
from scoring import (
    init_clients, load_resumes, batch_score,
    fetch_description, score_single, validate_models,
)
from scrapers.ats import fetch_all

# ── ATS-specific title filter ─────────────────────────────────────────────────
# Applied AFTER apply_filters() so it doesn't affect the JobSpy/SerpAPI pipelines.
#
# "experienced" — ATS boards explicitly label experienced vs. graduate roles.
#   On general job boards this word rarely appears in titles so filters.py
#   doesn't catch it. Here it reliably signals we're not the target audience.
#
# PhD-only full-time roles — identified by "(PhD)", "(PhD+)", "- PhD" in title
#   when NOT paired with "intern", "internship", "2026", or "2027" (which
#   would indicate a current-student or fresh-PhD program we could target).
_ATS_EXPERIENCED_RE = re.compile(r'\bexperienced\b', re.IGNORECASE)
_ATS_INTERN_RE     = re.compile(r'\bintern\b|\binternship\b|working\s+student', re.IGNORECASE)
# PhD-only full-time roles: drop unless paired with a grad-year (2026/2027/2028)
# which indicates a new-PhD hiring program rather than a multi-year post-doc role.
_ATS_PHD_RE        = re.compile(r'\bph\.?d\.?\b', re.IGNORECASE)
_ATS_PHD_KEEP_RE   = re.compile(r'202[678]', re.IGNORECASE)

# Unlike the job-board pipelines (JobSpy / SerpAPI), which search for specific
# terms and naturally surface entry-level results, the ATS scraper pulls every
# role from each company's board. Prop trading firms label graduate/junior
# programs explicitly, so we can require a positive early-career signal rather
# than relying on the absence of a seniority signal.
# Months that precede December — used to detect pre-Dec-2026 graduation cutoffs.
_MONTHS_PRE_DEC = (
    r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may'
    r'|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?)'
)
# Matches graduation deadlines that exclude a December 2026 graduate.
#
# Catches:
#   "graduating by Summer 2026"               — DV Trading 2026 role
#   "on track to graduate by Summer 2026"     — DV Trading Commodities role
#   "graduating between May 2025 and July 2026" — IMC Graduate Floor Trader
#   "graduating in 2028/29"                   — IMC Launchpad (too early for you)
#
# Does NOT catch:
#   "graduating by Summer 2027"               — Dec 2026 is before that, eligible
#   "graduation date between December 2026 and Spring 2027" — targets you exactly
_GRAD_CUTOFF_RE = re.compile(
    r'(?:graduating\b|on\s+track\s+to\s+graduate\b|graduation\s+(?:date|deadline)\b)'
    r'.{0,150}?'
    r'(?:'
    r'(?:spring|summer)\s+2026'         # seasons before Dec 2026
    r'|' + _MONTHS_PRE_DEC + r'\s+2026' # months Jan-Nov of 2026
    r'|20(?:23|24|25)\b'                # any 2025 or earlier graduation
    r'|202[89]\b'                       # 2028/2029 — discovery programs for freshmen
    r')',
    re.IGNORECASE | re.DOTALL,
)

_ATS_EARLY_CAREER_RE = re.compile(
    r'\bjunior\b|\bjr\.?\b'
    r'|\bgraduate\b'
    r'|\bcampus\b'
    r'|\bentry[\s-]level\b'
    r'|\bnew[\s-]grad(uate)?\b'
    r'|\bearly[\s-]career\b'
    r'|\bassociate\b'
    r'|\blaunchpad\b'
    r'|college\s+graduate|university\s+graduate'
    r'|expression\s+of\s+interest'   # Eclipse-style role-specific EOIs
    r'|202[678]'                      # class-year signals (2026/2027/2028)
    r'|\bmaster\'?s?\b|\bbachelor\'?s?\b|\bmsc\b|\bbsc\b'
    r'|\bundergraduate\b',
    re.IGNORECASE,
)


def _ats_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    ATS-specific post-filter applied after apply_filters().
    Does not touch the JobSpy / SerpAPI pipelines.

    Pass 1 — drop explicit negatives:
      • "Experienced [role]" titles
      • Internships / working-student roles (graduating Dec 2026, not eligible)
      • PhD-required full-time roles (no PhD exception for grad-year signals)

    Pass 2 — require explicit early-career signal:
      ATS boards include every open role, not just ones matching a search term,
      so unlabelled "Quantitative Researcher" at a top firm is almost certainly
      an experienced hire. Require junior/graduate/campus/class-year/etc. signal.
    """
    if df.empty:
        return df

    before = len(df)

    # Pass 1: explicit negatives
    exp_mask    = df["title"].apply(lambda t: bool(_ATS_EXPERIENCED_RE.search(str(t))))
    intern_mask = df["title"].apply(lambda t: bool(_ATS_INTERN_RE.search(str(t))))
    phd_mask    = df["title"].apply(
        lambda t: bool(_ATS_PHD_RE.search(str(t))) and not bool(_ATS_PHD_KEEP_RE.search(str(t)))
    )
    df = df[~(exp_mask | intern_mask | phd_mask)].copy()
    after_pass1 = len(df)

    # Pass 2: require early-career signal in title
    df = df[df["title"].apply(lambda t: bool(_ATS_EARLY_CAREER_RE.search(str(t))))].copy()
    after_pass2 = len(df)

    # Pass 3: graduation deadline check against description text.
    # Drops roles whose description reveals a graduation cutoff that excludes a
    # December 2026 graduate — either a deadline before Dec 2026 or a
    # far-future program meant for students still 2+ years from graduation.
    # Skipped when description is absent or too short to be reliable.
    def _has_early_cutoff(desc: str) -> bool:
        import html as _html
        if not desc or len(desc) < 100:
            return False
        # Second HTML-strip pass (handles entity-re-encoding edge cases)
        cleaned = re.sub(r"<[^>]+>", " ", _html.unescape(str(desc)))
        return bool(_GRAD_CUTOFF_RE.search(cleaned))

    grad_mask = df["description"].apply(_has_early_cutoff)
    if grad_mask.any():
        print("  ATS grad-cutoff filter dropped:")
        for _, r in df[grad_mask].iterrows():
            print(f"    − {r['company']}: {r['title']}")
    df = df[~grad_mask].copy()

    n_exp        = int(exp_mask.sum())
    n_intern     = int((intern_mask & ~exp_mask).sum())
    n_phd        = int((phd_mask & ~exp_mask & ~intern_mask).sum())
    n_unlabelled = after_pass1 - after_pass2
    n_grad       = int(grad_mask.sum())
    print(f"  ATS filter: {before} → {len(df)} "
          f"(−{n_exp} experienced, −{n_intern} internships, −{n_phd} PhD-only, "
          f"−{n_unlabelled} unlabelled, −{n_grad} wrong grad window)")
    return df


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
    print(f"ATS run — Direct company career pages    {ts}")
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

    # ── Phase 1: Fetch, filter, dedup ─────────────────────────────────────────
    print("1/3  Fetching existing Notion keys for dedup…")
    existing_keys = notion.get_existing_keys()
    print(f"     {len(existing_keys)} existing dedup keys\n")

    print("2/3  Fetching from ATS endpoints…")
    raw_df = fetch_all()
    print()

    if raw_df.empty:
        msg = f"🏢 *ATS* ({ts}) — all endpoints returned 0 results."
        print(msg)
        send_slack(msg)
        return

    print(f"     {len(raw_df)} raw listings fetched")
    filtered_df = apply_filters(raw_df)
    filtered_df = _ats_filter(filtered_df)

    if filtered_df.empty:
        msg = f"🏢 *ATS* ({ts}) — 0 jobs passed filters."
        print(msg)
        send_slack(msg)
        return

    net_new = filtered_df[~filtered_df.apply(
        lambda r: is_known_job(str(r.get("title", "")), str(r.get("company", "")),
                               str(r.get("location", "")), existing_keys),
        axis=1,
    )]
    skipped = len(filtered_df) - len(net_new)
    print(f"     {len(net_new)} net-new (skipped {skipped} already in Notion)\n")

    if net_new.empty:
        msg = (
            f"🏢 *ATS* ({ts}) — 0 net-new jobs after dedup "
            f"({len(filtered_df)} matched filters, all already in Notion)."
        )
        print(msg)
        send_slack(msg)
        return

    # ── Phase 2: Score + push ─────────────────────────────────────────────────
    print(f"3/3  Scoring and pushing {len(net_new)} jobs to Notion…\n")

    added          = 0
    visa_dropped   = 0
    failed_push    = []
    low_conf_queue = []
    jobs_list      = net_new.to_dict("records")

    for batch in _chunked(jobs_list, SCORING_BATCH_SIZE):
        scores = batch_score(batch, resumes, client,
                             fetch_missing=True, backup_client=backup)

        for job, score in zip(batch, scores):
            if score and score.visa_sponsored is False:
                print(f"    ✗ no visa — {job.get('title','')[:40]} @ {job.get('company','')[:20]}")
                visa_dropped += 1
                continue

            page_id = notion.push_job(job, score)
            if page_id:
                added += 1
                existing_keys.update(make_index_keys(
                    str(job.get("title", "")), str(job.get("company", "")),
                    str(job.get("location", ""))))
                print(f"    ✓ {job.get('title','')[:40]} @ {job.get('company','')[:20]}")
                if (score and score.low_confidence
                        and job.get("_was_no_desc") and not job.get("_fetched_chars")):
                    low_conf_queue.append((job, page_id))
            else:
                failed_push.append((job, score))

            time.sleep(0.35)

        time.sleep(5)

    # ── Phase 3: Low-confidence retries (up to 2 passes) ─────────────────────
    re_scored        = 0
    still_needs_desc = list(low_conf_queue)

    for retry_num in range(1, 3):
        if not still_needs_desc:
            break
        print(f"\n  ↺ Retry {retry_num}/2: {len(still_needs_desc)} job(s) missing descriptions…")
        next_round = []

        for job, page_id in still_needs_desc:
            time.sleep(5)
            fetched, visa_ok = fetch_description(
                client,
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                backup_client=backup,
            )
            if not fetched:
                print(f"    → still no description: {job.get('title','')[:40]}")
                next_round.append((job, page_id))
                continue
            if visa_ok is False:
                print(f"    ✗ no visa (re-scored) — {job.get('title','')[:40]}")
                visa_dropped += 1
                continue

            job["description"]    = fetched
            job["_fetched_chars"] = len(fetched)
            new_score = score_single(job, resumes, client, backup_client=backup)
            if new_score:
                if new_score.visa_sponsored is False:
                    print(f"    ✗ no visa (re-scored) — {job.get('title','')[:40]}")
                    visa_dropped += 1
                    continue
                new_score.low_confidence = False
                if notion.update_job_score(page_id, new_score, description=fetched):
                    re_scored += 1
                    print(f"    ✓ re-scored {new_score.fit_score}/10 — {job.get('title','')[:40]}")

        still_needs_desc = next_round

    if failed_push:
        print(f"\n  ✗ {len(failed_push)} job(s) failed to push to Notion:")
        for job, _ in failed_push:
            print(f"    • {job.get('title','')[:50]} @ {job.get('company','')[:25]}")

    # ── Phase 4: Slack summary ────────────────────────────────────────────────
    lines = [
        f"🏢 *ATS (Direct career pages)* — {ts}",
        f"✅ {added} added  |  ❌ {len(failed_push)} failed  |  "
        f"🔄 {re_scored}/{len(low_conf_queue)} re-scored  |  🚫 {visa_dropped} visa-denied",
    ]
    if skipped:
        lines.append(f"⏭ {skipped} skipped (already in Notion)")
    if failed_push:
        lines.append("⚠️ Failed pushes:")
        for job, _ in failed_push[:3]:
            lines.append(f"  – {job.get('title','')[:40]} @ {job.get('company','')[:20]}")
        if len(failed_push) > 3:
            lines.append(f"  …and {len(failed_push) - 3} more")

    msg = "\n".join(lines)
    print(f"\n{msg}")
    send_slack(msg)


if __name__ == "__main__":
    main()
