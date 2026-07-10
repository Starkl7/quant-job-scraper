"""
dedupe_notion.py — One-off cleanup pass over the Notion tracker.

Finds pages that collide on the (role, company, location) dedup key once
company legal suffixes are normalized away (e.g. "DV Trading" vs
"DV Trading LLC") — duplicates that slipped in before filters.make_dedup_key
stripped those suffixes. Keeps the oldest page in each duplicate group and
archives the rest.

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

from collections import defaultdict

import notion
from filters import make_dedup_key

DRY_RUN = True


def main() -> None:
    notion.validate_db()

    print("  Fetching all jobs from Notion…")
    pages = notion._query_database()
    print(f"  {len(pages)} total jobs\n")

    groups: dict[str, list[dict]] = defaultdict(list)
    for page in pages:
        props    = page.get("properties", {})
        role     = notion._title_text(props.get("Role",     {}))
        company  = notion._rich_text(props.get("Company",   {}))
        location = notion._rich_text(props.get("Location",  {}))
        if not role:
            continue
        key = make_dedup_key(role, company, location)
        groups[key].append({
            "page_id": page["id"],
            "created": page.get("created_time", ""),
            "role":    role,
            "company": company,
        })

    dupes = {k: v for k, v in groups.items() if len(v) > 1}
    if not dupes:
        print("  No duplicates found. Nothing to drop.")
        return

    to_archive = []
    print(f"  {len(dupes)} duplicate group(s) found:\n")
    for entries in dupes.values():
        entries.sort(key=lambda e: e["created"])
        keep, drop = entries[0], entries[1:]
        print(f"    KEEP  {keep['role']} @ {keep['company']}  ({keep['created']})")
        for d in drop:
            print(f"    DROP  {d['role']} @ {d['company']}  ({d['created']})")
            to_archive.append(d["page_id"])
        print()

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
