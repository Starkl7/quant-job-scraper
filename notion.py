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
from candidates import Candidate, get_configured_candidates

HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Content-Type":   "application/json",
    "Notion-Version": NOTION_API_VERSION,
}

_MAX_PUSH_RETRIES = 2   # push_job retries on transient Notion errors


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

def get_existing_keys() -> set[str]:
    """
    Query Notion for all existing entries and return their dedup keys.
    Paginates automatically. Used to prevent cross-run duplicates.
    """
    url     = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    payload = {"page_size": 100}
    keys: set[str] = set()

    while True:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Notion query failed ({resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json()
        for page in data.get("results", []):
            props    = page.get("properties", {})
            role     = _title_text(props.get("Role",     {}))
            company  = _rich_text(props.get("Company",   {}))
            location = _rich_text(props.get("Location",  {}))
            if role:
                from filters import make_dedup_key
                keys.add(make_dedup_key(role, company, location))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    return keys


# ── Write — create new page ────────────────────────────────────────────────────

def push_job(row: pd.Series, scores=None, candidates: list[Candidate] | None = None) -> "str | bool":
    """
    Create one Notion page for a job listing.

    Returns the new page_id (str) on success, or False on failure.
    The page_id is used by the orchestrator's low-confidence retry pass to
    PATCH an updated score once a description is fetched.

    Args:
        row:   pd.Series — keys: title, company, location, site, job_url,
               description, min_amount, max_amount, date_posted
        scores: dict[candidate_id, ScoreResult] or a single ScoreResult (legacy)
        candidates: optional list of Candidate configs for column names
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

    # Inline scoring fields (per-candidate columns)
    score_props = _score_properties(scores, candidates)
    if score_props:
        payload["properties"].update(score_props)

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

def update_job_score(
    page_id: str,
    scores,
    description: str = "",
    candidates: list[Candidate] | None = None,
) -> bool:
    """
    PATCH an existing Notion page with updated scoring fields only.
    Used by the low-confidence retry pass after a description is fetched.
    Also writes Description if provided.

    Args:
        scores: dict[candidate_id, ScoreResult] or a single ScoreResult (legacy)
    """
    score_props = _score_properties(scores, candidates)
    if not score_props:
        return False

    payload: dict = {"properties": score_props}
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _normalize_scores(scores, candidates: list[Candidate] | None = None) -> list[tuple[Candidate, object]]:
    """Convert legacy single ScoreResult or dict into [(Candidate, ScoreResult), ...]."""
    if scores is None:
        return []

    active = candidates or get_configured_candidates()

    if isinstance(scores, dict):
        out = []
        for candidate in active:
            score = scores.get(candidate.id)
            if score is not None:
                out.append((candidate, score))
        return out

    if len(active) == 1:
        return [(active[0], scores)]
    if len(active) > 1:
        raise ValueError(
            "Multiple candidates configured but push_job received a single ScoreResult. "
            "Pass a dict[candidate_id, ScoreResult] instead."
        )
    return [(Candidate(
        id="legacy",
        display_name="Legacy",
        resume_folder_env="",
        resume_labels=("QT", "QR", "QA", "Risk"),
        fit_score_col="Fit Score",
        best_resume_col="Best Resume",
        ai_notes_col="AI Notes",
        system_prompt="",
    ), scores)]


def _score_properties(scores, candidates: list[Candidate] | None = None) -> dict:
    props: dict = {}
    for candidate, score in _normalize_scores(scores, candidates):
        props[candidate.fit_score_col] = {"number": int(score.fit_score)}
        props[candidate.best_resume_col] = {"select": {"name": score.best_resume}}
        props[candidate.ai_notes_col] = {
            "rich_text": [{"text": {"content": _format_ai_notes(score)[:2000]}}]
        }
    return props


def _rich_text(prop: dict) -> str:
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))


def _title_text(prop: dict) -> str:
    return "".join(t.get("plain_text", "") for t in prop.get("title", []))


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
