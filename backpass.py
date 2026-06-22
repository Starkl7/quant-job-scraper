"""
backpass.py — One-off cleanup pass over the Notion tracker.

Archives listings where BOTH Fit Score-Dhrubo and Fit Score-Shreyansh are
present and both are <= THRESHOLD. A listing is left alone if either score
is missing (not yet scored) or either score is above THRESHOLD.

Archiving is a Notion soft-delete: the page disappears from the database/board
but is recoverable from Notion's Trash for ~30 days.

NOT FOR GITHUB ACTIONS — run locally only.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODES  (toggle DRY_RUN below)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  True  — (default) print what would be archived, archive nothing.
  False — actually archive the matching pages.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run: python backpass.py
"""

from dotenv import load_dotenv
load_dotenv()

import notion

DRY_RUN   = True
THRESHOLD = 4


def should_drop(job: dict) -> bool:
    d, s = job["fit_dhrubo"], job["fit_shreyansh"]
    if d is None or s is None:
        return False
    return d <= THRESHOLD and s <= THRESHOLD


def main() -> None:
    notion.validate_db()

    print("  Fetching all jobs from Notion…")
    jobs = notion.get_scored_jobs()
    print(f"  {len(jobs)} total jobs\n")

    candidates = [j for j in jobs if should_drop(j)]

    if not candidates:
        print(f"  No listings with both scores <= {THRESHOLD}. Nothing to drop.")
        return

    print(f"  {len(candidates)} listing(s) qualify to drop (both scores <= {THRESHOLD}):\n")
    for j in candidates:
        print(f"    [D:{j['fit_dhrubo']} S:{j['fit_shreyansh']}]  {j['role']} @ {j['company']}")

    if DRY_RUN:
        print(f"\n  DRY_RUN=True — nothing archived. Set DRY_RUN=False to actually archive these {len(candidates)} listing(s).")
        return

    print(f"\n  Archiving {len(candidates)} listing(s)…")
    archived, failed = 0, 0
    for j in candidates:
        if notion.archive_page(j["page_id"]):
            archived += 1
        else:
            failed += 1
    print(f"  Done — archived {archived}, failed {failed}.")


if __name__ == "__main__":
    main()
