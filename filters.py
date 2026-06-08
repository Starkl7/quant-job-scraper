"""
filters.py — Job filtering logic.
Pure functions and compiled regexes. No I/O, no API calls.
"""

import re
import pandas as pd

# ── Senior-title exclusion patterns ──────────────────────────────────────────
# Hard-exclude if ANY of these appear in the job title (case-insensitive).
# We don't require an explicit new-grad signal because many quant firms post
# entry-level roles without labels (e.g. "Quantitative Researcher" at
# Citadel/Two Sigma/Jane Street for new PhD/MSc grads).

SENIOR_TITLE_PATTERNS: list[str] = [
    "senior", r"\bsr\b", "lead ", "principal", "director",
    r"\bvp\b", "vice president", "head of", "managing director",
    r"\bmd\b", "manager", "staff quant", "chief ", "partner",
]
_SENIOR_RE = re.compile(
    "|".join(SENIOR_TITLE_PATTERNS), flags=re.IGNORECASE
)

# ── Early-career / grad-year signals ─────────────────────────────────────────

GRAD_SIGNALS: list[str] = [
    "new grad", "new graduate", "entry level", "entry-level",
    "early career", "early-career", "junior", "associate",
    "recent graduate", "newly graduated",
    "graduating 2026", "graduating 2027",
    "class of 2026", "class of 2027",
    "0-2 year", "0 to 2 year",
    "no prior experience", "no experience required",
    "december 2026", "may 2027", "spring 2027", "winter 2026",
]
_GRAD_RE = re.compile(
    "|".join(re.escape(s) for s in GRAD_SIGNALS), flags=re.IGNORECASE
)

# ── Quant-title relevance gate ────────────────────────────────────────────────
# Title must contain at least one of these to pass; catches unrelated roles
# that slipped in because "quantitative" appeared in the description.

_QUANT_TITLE_RE = re.compile(
    r'\bquant\b|quantitative|\balgo\b|algorithmic|\btrader\b|researcher'
    r'|strategist|risk\s+analyst|model\s+(?:risk|validat)',
    flags=re.IGNORECASE,
)

# ── Company blocklist ─────────────────────────────────────────────────────────
# Annotation / gig platforms that post quant-sounding titles for labelling work.
# Recruitment agencies are NOT blocked — they post real finance roles.

COMPANY_BLOCKLIST: frozenset[str] = frozenset({
    "dataannotation",
    "outlier",
    "scale ai",
    "appen",
    "remotasks",
    "telus international",
    "lionbridge",
})

# ── Experience extraction ─────────────────────────────────────────────────────
# Pulls "X years experience" phrases for display in Notion Notes.
# Wider than the old binary filter — captures any X-year phrase for review.

_EXP_EXTRACT_RE = re.compile(
    r'(?:'
    r'\b(?:[0-9]|[1-9][0-9])\+?\s*(?:[-–]\s*\d+\s*)?years?[^.;\n]{0,60}?experience'
    r'|minimum\s+(?:of\s+)?(?:[0-9]|[1-9][0-9])\+?\s+years?[^.;\n]{0,40}'
    r'|at\s+least\s+(?:[0-9]|[1-9][0-9])\+?\s+years?[^.;\n]{0,40}'
    r')',
    flags=re.IGNORECASE,
)


# Strips location noise so cross-source dedup keys match.
# "(+5 others)" — SerpAPI multi-city suffix
# ", USA" / ", United States" / ", US" — country suffix LinkedIn sometimes appends
_LOCATION_SUFFIX_RE = re.compile(
    r'\s*\(\+\d+\s+others?\)\s*$'           # (+5 others)
    r'|,\s*(?:usa|united states|u\.s\.a?\.)$'  # , USA  / , United States
    r'|,\s*(?:uk|united kingdom|u\.k\.)\s*$',  # , UK   / , United Kingdom
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    text = re.sub(r'\s+', ' ', text.lower().strip())
    return _LOCATION_SUFFIX_RE.sub('', text).strip()


def make_dedup_key(role: str, company: str, location: str) -> str:
    return f"{_norm(role)}|{_norm(company)}|{_norm(location)}"


def extract_exp_req(desc: str) -> str:
    """Extract all experience-requirement phrases from a description."""
    hits = _EXP_EXTRACT_RE.findall(desc)
    unique: list[str] = []
    seen: set[str] = set()
    for m in hits:
        m = m.strip()
        if m.lower() not in seen:
            seen.add(m.lower())
            unique.append(m)
    return " | ".join(unique)


def filter_reason(row: pd.Series) -> tuple[bool, str]:
    """Return (passed, reason_string). Used by dry_run.py for verbose output."""
    title   = str(row.get("title",   ""))
    desc    = str(row.get("description", ""))
    company = str(row.get("company", ""))

    if not _QUANT_TITLE_RE.search(title):
        return False, "EXCLUDED — no quant signal in title"

    company_norm = _norm(company)
    if any(blocked in company_norm for blocked in COMPANY_BLOCKLIST):
        return False, f"EXCLUDED — company blocklist: '{company}'"

    senior_hit = _SENIOR_RE.search(title)
    if senior_hit:
        return False, f"EXCLUDED — senior signal in title: '{senior_hit.group()}'"

    grad_in_title = _GRAD_RE.search(title)
    if grad_in_title:
        return True, f"PASSED  — early-career signal in title: '{grad_in_title.group()}'"

    grad_in_desc = _GRAD_RE.search(desc)
    if grad_in_desc:
        return True, f"PASSED  — early-career signal in description: '{grad_in_desc.group()}'"

    return True, "PASSED  — no seniority signal (unlabelled new-grad role, kept for review)"


def is_early_career(row: pd.Series) -> bool:
    return filter_reason(row)[0]


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply all filters to a raw DataFrame. Returns filtered copy with
    _dedup_key and _tc_key columns added.
    """
    if df.empty:
        return df

    df = df.copy()

    # Add dedup keys
    df["_dedup_key"] = df.apply(
        lambda r: make_dedup_key(
            str(r.get("title", "")),
            str(r.get("company", "")),
            str(r.get("location", "")),
        ),
        axis=1,
    )

    # Within-run dedup: same role + company + location
    before = len(df)
    df = df.drop_duplicates(subset=["_dedup_key"])

    # Secondary dedup: same title + company across different locations (keep first)
    df["_tc_key"] = df.apply(
        lambda r: f"{_norm(str(r.get('title', '')))}|{_norm(str(r.get('company', '')))}",
        axis=1,
    )
    df = df.drop_duplicates(subset=["_tc_key"])
    after_dedup = len(df)

    # Early-career filter
    df = df[df.apply(is_early_career, axis=1)].copy()

    print(
        f"  Filters: {before} raw → {after_dedup} after dedup "
        f"→ {len(df)} after early-career filter"
    )
    return df
