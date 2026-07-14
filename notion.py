"""
notion.py — Notion API layer.
All reads and writes go through here. Nothing else in the codebase
touches the Notion REST API directly.
"""

import time
import re
import requests
import pandas as pd

from config import NOTION_TOKEN, NOTION_DB_ID, NOTION_API_VERSION, SOURCE_MAP
from filters import extract_exp_req

HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Content-Type":   "application/json",
    "Notion-Version": NOTION_API_VERSION,
}

_MAX_PUSH_RETRIES = 2   # retries on transient Notion errors (push, update, query)


# ── Startup validation ─────────────────────────────────────────────────────────

def validate_db() -> None:
    """
    Confirm that NOTION_TOKEN can reach NOTION_DB_ID.
    Raises RuntimeError with a clear message if the DB is unreachable — catches
    missing integration permissions and wrong DB IDs before any jobs are pushed.
    """
    url  = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code == 200:
        title = resp.json().get("title", [{}])[0].get("plain_text", NOTION_DB_ID)
        print(f"  ✓ Notion DB reachable: \"{title}\"")
        return
    if resp.status_code == 404:
        raise RuntimeError(
            f"Notion DB not found (404). Check NOTION_DB_ID and ensure the "
            f"integration is added to the database (Share → Invite → your integration)."
        )
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Notion auth failed ({resp.status_code}). Check NOTION_TOKEN."
        )
    raise RuntimeError(
        f"Notion DB check failed ({resp.status_code}): {resp.text[:200]}"
    )


# ── Read ───────────────────────────────────────────────────────────────────────

def _query_database() -> list[dict]:
    """
    Page through the entire database, retrying transient failures per page.
    Returns the raw list of Notion page objects.
    """
    url     = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    payload = {"page_size": 100}
    pages: list[dict] = []

    while True:
        for attempt in range(_MAX_PUSH_RETRIES + 1):
            resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
            if resp.status_code == 200:
                break
            if attempt < _MAX_PUSH_RETRIES:
                print(f"    ⚠ Notion query attempt {attempt+1} failed ({resp.status_code}) — retrying in 3s…")
                time.sleep(3)
        else:
            raise RuntimeError(
                f"Notion query failed ({resp.status_code}) after {_MAX_PUSH_RETRIES+1} attempts: {resp.text[:300]}"
            )
        data = resp.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    return pages


def get_existing_keys() -> set[str]:
    """
    Query Notion for all existing entries and return their dedup-index keys
    (one per city, plus presence/wildcard markers — see filters.make_index_keys).
    Used with filters.is_known_job() to prevent cross-run duplicates.
    """
    from filters import make_index_keys

    keys: set[str] = set()
    for page in _query_database():
        props    = page.get("properties", {})
        role     = _title_text(props.get("Role",     {}))
        company  = _rich_text(props.get("Company",   {}))
        location = _rich_text(props.get("Location",  {}))
        if role:
            keys.update(make_index_keys(role, company, location))
    return keys


def get_scored_jobs() -> list[dict]:
    """
    Return every page with both fit-score columns plus role/company for display.
    Each item: page_id, role, company, fit_dhrubo, fit_shreyansh (None if unscored).
    """
    jobs = []
    for page in _query_database():
        props = page.get("properties", {})
        jobs.append({
            "page_id":       page["id"],
            "role":          _title_text(props.get("Role",     {})),
            "company":       _rich_text(props.get("Company",   {})),
            "fit_dhrubo":    _number(props.get("Fit Score-Dhrubo",    {})),
            "fit_shreyansh": _number(props.get("Fit Score-Shreyansh", {})),
        })
    return jobs


# ── Write — create new page ────────────────────────────────────────────────────

def push_job(row: pd.Series, score=None) -> "str | bool":
    """
    Create one Notion page for a job listing.

    Returns the new page_id (str) on success, or False on failure.
    The page_id is used by the orchestrator's low-confidence retry pass to
    PATCH an updated score once a description is fetched.

    Args:
        row:   pd.Series — keys: title, company, location, site, job_url,
               description, min_amount, max_amount, date_posted
        score: optional ScoreResult from scoring.py
    """
    source   = SOURCE_MAP.get(str(row.get("site", "")).lower(), "Other")
    title    = str(row.get("title",    "Unknown Role"))[:2000]
    company  = str(row.get("company",  ""))[:2000]
    location = str(row.get("location", ""))[:2000]
    url      = str(row.get("job_url",  "")) or None

    exp_req = extract_exp_req(str(row.get("description", "")))

    payload: dict = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Role":     {"title":     [{"text": {"content": title}}]},
            "Company":  {"rich_text": [{"text": {"content": company}}]},
            "Location": {"rich_text": [{"text": {"content": location}}]},
            "Source":   {"select":    {"name": source}},
            "Status":   {"select":    {"name": "To Apply"}},
        },
    }

    if url:
        payload["properties"]["Apply Link"] = {"url": url}

    # Notes: salary + experience requirement
    notes_parts = []
    salary_str  = _salary_str(row)
    if salary_str:
        notes_parts.append(f"Salary: {salary_str}")
    if exp_req:
        notes_parts.append(f"Exp: {exp_req}")
    if notes_parts:
        payload["properties"]["Notes"] = {
            "rich_text": [{"text": {"content": " | ".join(notes_parts)[:2000]}}]
        }

    # Description (Gemma-generated or scraped — written here so Notion shows it)
    raw_desc = str(row.get("description", "")).strip()
    if raw_desc and raw_desc.lower() not in ("nan", "none", ""):
        payload["properties"]["Description"] = {
            "rich_text": [{"text": {"content": raw_desc[:2000]}}]
        }

    # Inline scoring fields
    if score is not None:
        payload["properties"]["Fit Score-Dhrubo"]   = {"number": int(score.fit_score)}
        payload["properties"]["Best Resume-Dhrubo"] = {"select": {"name": score.best_resume}}
        payload["properties"]["AI Notes-Dhrubo"]    = {
            "rich_text": [{"text": {"content": _format_ai_notes(score)[:2000]}}]
        }

    for attempt in range(_MAX_PUSH_RETRIES + 1):
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("id", True)   # return page_id
        if attempt < _MAX_PUSH_RETRIES:
            print(f"    ⚠ Notion push attempt {attempt+1} failed ({resp.status_code}) — retrying in 3s…")
            time.sleep(3)

    print(f"    ✗ Notion push FAILED after {_MAX_PUSH_RETRIES+1} attempts: {title} @ {company} — {resp.text[:120]}")
    return False


# ── Write — update existing page ───────────────────────────────────────────────

def update_job_score(page_id: str, score, description: str = "") -> bool:
    """
    PATCH an existing Notion page with updated scoring fields only.
    Used by the low-confidence retry pass after a description is fetched.
    Also writes Description if provided.
    """
    ai_notes = _format_ai_notes(score)

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

    for attempt in range(_MAX_PUSH_RETRIES + 1):
        resp = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            return True
        if attempt < _MAX_PUSH_RETRIES:
            time.sleep(3)

    print(f"    ✗ update_job_score failed ({resp.status_code}): {resp.text[:120]}")
    return False


def archive_page(page_id: str) -> bool:
    """
    Archive a Notion page (soft-delete — recoverable from Notion's Trash for ~30 days).
    """
    payload = {"archived": True}
    for attempt in range(_MAX_PUSH_RETRIES + 1):
        resp = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            return True
        if attempt < _MAX_PUSH_RETRIES:
            time.sleep(3)

    print(f"    ✗ archive_page failed ({resp.status_code}): {resp.text[:120]}")
    return False


# ── Helpers ────────────────────────────────────────────────────────────────────

def _rich_text(prop: dict) -> str:
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))


def _title_text(prop: dict) -> str:
    return "".join(t.get("plain_text", "") for t in prop.get("title", []))


def _number(prop: dict) -> "float | None":
    return prop.get("number")


def _salary_str(row: pd.Series) -> str:
    try:
        lo = row.get("min_amount")
        hi = row.get("max_amount")
        if pd.notna(lo) and pd.notna(hi):
            return f"${int(lo):,} – ${int(hi):,}"
        if pd.notna(lo):
            return f"${int(lo):,}+"
        if pd.notna(hi):
            return f"Up to ${int(hi):,}"
    except (ValueError, TypeError):
        pass
    return ""


def _format_ai_notes(score) -> str:
    """
    AI Notes = Strengths + Weaknesses only.
    Fit Score and Best Resume live in their own dedicated columns.
    """
    parts = []
    if score.strengths:
        parts.append(f"Strengths: {score.strengths}")
    if score.weaknesses:
        parts.append(f"Weaknesses: {score.weaknesses}")
    if score.low_confidence:
        parts.append("⚠ Scored on title/company only — no description available")
    return "\n".join(parts)
