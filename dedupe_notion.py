"""
dedupe_notion.py — One-off cleanup pass over the Notion tracker.

Replays every page (oldest first) through the same cross-run dedup logic the
orchestrators use (filters.match_existing / make_index_keys), so it flags any
page that would have been skipped as a duplicate had it arrived today:

  • same title+company+city once company aliases and legal suffixes are
    normalized away (e.g. "Old Mission Capital" vs "Old Mission")
  • multi-city listings that overlap an existing single-city one
    (e.g. "Chicago, IL or New York, NY" vs "New York, NY")
  • location-less re-listings ("", "Anywhere", "Remote") of a job already
    tracked with a real city, and vice versa

Same title+company in *different* real cities is NOT a duplicate — each city
stays a distinct entry. Keeps the oldest page in each group, archives the rest.

Archiving is a Notion soft-delete: the page disappears from the database/board
but is recoverable from Notion's Trash for ~30 days.

NOT FOR GITHUB ACTIONS — run locally only.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODES  (toggle DRY_RUN below)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  True  — (default) print duplicate groups, archive nothing.
  False — actually archive the newer duplicate(s) in each group.

Run: python dedupe_notion.py
"""

from dotenv import load_dotenv
load_dotenv()

import notion
from filters import make_index_keys, match_existing

DRY_RUN = True


def main() -> None:
    notion.validate_db()

    print("  Fetching all jobs from Notion…")
    pages = notion._query_database()
    print(f"  {len(pages)} total jobs\n")

    entries = []
    for page in pages:
        props    = page.get("properties", {})
        role     = notion._title_text(props.get("Role",     {}))
        company  = notion._rich_text(props.get("Company",   {}))
        location = notion._rich_text(props.get("Location",  {}))
        if not role:
            continue
        entries.append({
            "page_id":  page["id"],
            "created":  page.get("created_time", ""),
            "role":     role,
            "company":  company,
            "location": location,
        })
    entries.sort(key=lambda e: e["created"])

    # Replay oldest-first: the first page to claim a key is kept, any later
    # page that matches the index is a duplicate of whichever page owns the
    # matched key.
    index: set[str] = set()
    owner: dict[str, dict] = {}     # index key → page that first claimed it
    dupes: list[tuple[dict, dict]] = []  # (duplicate page, kept page)

    for e in entries:
        hit = match_existing(e["role"], e["company"], e["location"], index)
        if hit:
            dupes.append((e, owner[hit]))
            continue
        for key in make_index_keys(e["role"], e["company"], e["location"]):
            index.add(key)
            owner.setdefault(key, e)

    if not dupes:
        print("  No duplicates found. Nothing to drop.")
        return

    print(f"  {len(dupes)} duplicate(s) found:\n")
    to_archive = []
    for drop, keep in dupes:
        print(f"    KEEP  {keep['role']} @ {keep['company']} [{keep['location']}]  ({keep['created'][:10]})")
        print(f"    DROP  {drop['role']} @ {drop['company']} [{drop['location']}]  ({drop['created'][:10]})")
        print()
        to_archive.append(drop["page_id"])

    if DRY_RUN:
        print(f"  DRY_RUN=True — nothing archived. Set DRY_RUN=False to archive these {len(to_archive)} duplicate(s).")
        return

    print(f"  Archiving {len(to_archive)} duplicate(s)…")
    archived, failed = 0, 0
    for page_id in to_archive:
        if notion.archive_page(page_id):
            archived += 1
        else:
            failed += 1
    print(f"  Done — archived {archived}, failed {failed}.")


if __name__ == "__main__":
    main()
