"""
backpass_exclusions.py — One-off cleanup pass over the Notion tracker.

Archives listings that violate the current exclusion rules but were pushed
before those rules existed:
  - internship / co-op / summer-analyst titles (filters.INTERN_PATTERNS)
  - blocked companies (filters.COMPANY_BLOCKLIST)

Archiving is a Notion soft-delete: the page disappears from the database/board
but is recoverable from Notion's Trash for ~30 days.

NOT FOR GITHUB ACTIONS — run locally only.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODES  (toggle DRY_RUN below)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  True  — (default) print what would be archived, archive nothing.
  False — actually archive the matching pages.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run: python backpass_exclusions.py
"""

from dotenv import load_dotenv
load_dotenv()

import notion
from filters import _INTERN_RE, COMPANY_BLOCKLIST, _norm

DRY_RUN = True


def reason_to_drop(job: dict) -> "str | None":
    title        = job["role"] or ""
    company_norm = _norm(job["company"] or "")

    intern_hit = _INTERN_RE.search(title)
    if intern_hit:
        return f"internship signal in title: '{intern_hit.group()}'"

    blocked = next((b for b in COMPANY_BLOCKLIST if b in company_norm), None)
    if blocked:
        return f"blocked company: '{job['company']}'"

    return None


def main() -> None:
    notion.validate_db()

    print("  Fetching all jobs from Notion…")
    jobs = notion.get_scored_jobs()
    print(f"  {len(jobs)} total jobs\n")

    candidates = []
    for j in jobs:
        reason = reason_to_drop(j)
        if reason:
            candidates.append((j, reason))

    if not candidates:
        print("  No listings match the exclusion rules. Nothing to drop.")
        return

    print(f"  {len(candidates)} listing(s) qualify to drop:\n")
    for j, reason in candidates:
        print(f"    [{reason}]  {j['role']} @ {j['company']}")

    if DRY_RUN:
        print(f"\n  DRY_RUN=True — nothing archived. Set DRY_RUN=False to actually archive these {len(candidates)} listing(s).")
        return

    print(f"\n  Archiving {len(candidates)} listing(s)…")
    archived, failed = 0, 0
    for j, _ in candidates:
        if notion.archive_page(j["page_id"]):
            archived += 1
        else:
            failed += 1
    print(f"  Done — archived {archived}, failed {failed}.")


if __name__ == "__main__":
    main()
