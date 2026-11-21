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
    # Added Nov 2026 (live sample): mid-career postings that slipped through
    r"experienced\s+hire", r"\b(?:iii|iv)\b", r"re-?entry",
]
_SENIOR_RE = re.compile(
    "|".join(SENIOR_TITLE_PATTERNS), flags=re.IGNORECASE
)

# ── Internship exclusion ──────────────────────────────────────────────────────
# Hard-exclude internships/co-ops regardless of any grad-year signal in the
# title or description — grad-year phrasing ("class of 2026", "graduating
# 2026") appears on internship postings too, so this check must run before
# the grad-signal check, not rely on it.

INTERN_PATTERNS: list[str] = [
    r"\bintern\b", r"\binterns\b", "internship", r"\bco-?op\b",
    "summer analyst", "summer associate",
    r"\bstage\b",   # French-style internship ("Quant Developer Stage")
]
_INTERN_RE = re.compile(
    "|".join(INTERN_PATTERNS), flags=re.IGNORECASE
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

# STRONG signals: unambiguous quant-finance vocabulary.
_STRONG_TITLE_RE = re.compile(
    r'\bquant\b|quantitative|\balgo\b|algorithmic|\btrader\b|researcher'
    r'|strategist|risk\s+analyst|model\s+(?:risk|validat)',
    flags=re.IGNORECASE,
)

# WEAK signals (added Nov 2026 after a live sample showed real roles rejected, e.g.
# "Systematic Derivatives - Associate", "Junior Trading Analyst", "Associate, Model
# Development"). Each needs a finance qualifier, and a weak-only title is ALSO run
# through the denylist + energy/sales/etc. extras (see noise_hit) because words like
# "modeling" / "systematic" / "derivatives" appear in plenty of non-finance titles.
_WEAK_TITLE_RE = re.compile(
    r'systematic\s+(?:trading|credit|equit|macro|derivativ|strateg|research|invest)'
    r'|trading\s+analyst'
    r'|derivatives?\s+(?:trad|struct|quant|analyst|pricing|research)'
    r'|(?:credit|risk|market|financial|loss|prepayment|margin|mortgage|pricing)\w*\s+model(?:l?er|l?ing)\b'
    r'|model\s+develop'
    r'|strategies\s+research'
    r'|\bstrats?\b|stress\s+test|\bccar\b|\bcecl\b|risk\s+(?:developer|engineer)|\bfrtb\b',
    flags=re.IGNORECASE,
)

_QUANT_TITLE_RE = re.compile(_STRONG_TITLE_RE.pattern + "|" + _WEAK_TITLE_RE.pattern,
                             flags=re.IGNORECASE)

# New-grad program titles that carry no quant keyword — bank/consulting 2027
# programs like "2027 Markets Full-Time Analyst Program" or "Strategy
# Consulting Associate - 2027". A year near analyst/associate/graduate, or an
# explicit program/new-grad phrase, passes the gate; Gemini scoring downstream
# handles relevance.

_PROGRAM_TITLE_RE = re.compile(
    r'\b20\d{2}\b.{0,40}\b(?:analyst|associate|graduate|program)\b'
    r'|\b(?:analyst|associate|graduate)\b.{0,40}\b20\d{2}\b'
    r'|analyst\s+program|graduate\s+program|new\s+grad'
    r'|campus\s+(?:hire|analyst|associate)|strategy\s+consult',
    flags=re.IGNORECASE,
)

# ── Non-quant function denylist ───────────────────────────────────────────────
# Applied ONLY to titles that have no quant signal and got in via the new-grad
# program pattern (e.g. "2027 Associate - Audit"). A quant-titled role is never
# denied by this list. Nov 2026: ~44% of net-new jobs in a run were these.
# Kept deliberately narrow — investment banking / consulting / markets programs
# are NOT listed: those are an explicit goal of the new-grad cluster.

_NONQUANT_NOISE_RE = re.compile(
    r"\baudit\b|\btax\b|accounting|\baccountant\b|bookkeep|payroll|"
    r"employee\s+benefits|account\s+rep|account\s+manager|insurance|"
    r"supply\s+chain|logistics|procurement|"
    r"mechanical|civil\b|electrical\s+engineer|structural|chemical\s+engineer|"
    r"nurs(?:e|ing)|pharmac|clinical|\bdental|"
    r"talent\s+acquisition|recruit(?:er|ing)|human\s+resources|\bhr\b|"
    r"paralegal|legal\s+assistant|"
    r"client\s+service|customer\s+(?:service|success|support)|"
    r"sales\s+(?:associate|representative|rep)|business\s+development\s+rep|"
    r"commercial\s+lines|claims|underwrit|real\s+estate|\bplanning\s+new\s+grad|"
    r"marketing|content|graphic|\bretail\b|store\s+|warehouse|"
    r"\bgbs\b|\bgldp\b|onetech|rotational\s+program\s*[-|]\s*(?:operations|hr)",
    flags=re.IGNORECASE,
)


# Extra deny terms applied only to weak-signal-only titles (e.g. "Energy Trading Analyst").
_WEAK_EXTRA_NOISE_RE = re.compile(
    r"energy|power|commodit|natural\s+gas|\boil\b|hydro|clinical|pharma|claims|"
    r"catastroph|wealth|sales|marketing|simulation|3d|world\s+model|merchandis",
    flags=re.IGNORECASE,
)


def noise_hit(title: str) -> str:
    """Matched noise term for a title without a STRONG quant signal, else ''."""
    if _STRONG_TITLE_RE.search(title):
        return ""
    m = _NONQUANT_NOISE_RE.search(title)
    if m:
        return m.group()
    if _WEAK_TITLE_RE.search(title):
        m = _WEAK_EXTRA_NOISE_RE.search(title)
        return m.group() if m else ""
    return ""


# ── Company blocklist ─────────────────────────────────────────────────────────
# Annotation / gig platforms that post quant-sounding titles for labelling work.
# Recruitment agencies are NOT blocked — they post real finance roles.
# Prop trading firms that require the trader to fund/risk their own capital
# (not W-2 employment) are also blocked — e.g. T3 Trading.

COMPANY_BLOCKLIST: frozenset[str] = frozenset({
    "dataannotation",
    "outlier",
    "scale ai",
    "appen",
    "remotasks",
    "telus international",
    "lionbridge",
    "t3 trading",
    "mysmartpros",
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
    r'|,\s*(?:uk|united kingdom|u\.k\.)\s*$'   # , UK   / , United Kingdom
    r'|,\s*hong kong sar\s*$',                 # , Hong Kong SAR
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    text = re.sub(r'\s+', ' ', text.lower().strip())
    return _LOCATION_SUFFIX_RE.sub('', text).strip()


# Strips trailing legal-entity suffixes so cross-source dedup keys match
# regardless of whether a source appends one, e.g. "DV Trading" vs "DV Trading LLC".
_COMPANY_SUFFIX_RE = re.compile(
    r',?\s*\b(llc|inc|incorporated|corp|corporation|ltd|limited|llp|lp|plc|co)\.?\s*$',
    re.IGNORECASE,
)


# Known brand-name variants across sources (ATS posts the legal name, Google
# Jobs/LinkedIn the brand). Keys and values are post-suffix-strip normalized
# forms; every variant maps to one canonical spelling. Hand-curated only — no
# fuzzy/prefix matching, because near-identical names can be distinct firms
# (e.g. Citadel vs Citadel Securities, deliberately NOT aliased).
COMPANY_ALIASES: dict[str, str] = {
    "old mission capital": "old mission",
    "aquatic capital management": "aquatic capital",
    "da vinci trading": "da vinci",
    "imc": "imc trading",
    "imc financial markets": "imc trading",
    "epam systems": "epam",
    "vanguard careers": "vanguard",
    "synchrony financial": "synchrony",
    "regions financial": "regions",
    "clearwater analytics (cwan)": "clearwater analytics",
    "innova solutions": "innova",
    "td securities": "td",
}


def _norm_company(text: str) -> str:
    name = _COMPANY_SUFFIX_RE.sub('', _norm(text)).strip()
    return COMPANY_ALIASES.get(name, name)


# Location strings that carry no real place information. A job whose location
# reduces to one of these is treated as "location unknown" for cross-run dedup.
# Country/state names are deliberately NOT here: "United States" is kept as a
# distinct location so a genuinely new US posting is never swallowed by an
# existing posting elsewhere (e.g. a Sydney-only firm opening a US role).
WILDCARD_LOCATIONS: frozenset[str] = frozenset({
    "", "anywhere", "remote", "worldwide", "global", "flexible",
})


def _split_locations(text: str) -> list[str]:
    """
    Split a possibly multi-city location string into normalized city names:

      "New York, United States"                → ["new york"]
      "Chicago, IL or New York, NY"            → ["chicago", "new york"]
      "chicago; new york"                      → ["chicago", "new york"]
      "Greater Toronto Area, Canada"           → ["toronto"]
      "London Area, United Kingdom"            → ["london"]
      "Anywhere"                               → [] (wildcard, no real city)

    Each city is the part of its segment before the first comma; the rest is
    state/province/country. Wildcard segments (see WILDCARD_LOCATIONS) are
    dropped, so an all-wildcard location returns [].
    """
    text = _norm(text)
    cities: list[str] = []
    # Multi-city separators: "chicago; new york", "Chicago/Miami", "A or B", "A and B".
    # \bor\b also matches a trailing ", OR" state abbreviation — harmless, since
    # the empty segment it leaves behind is dropped below.
    for part in re.split(r'[;/|]|\bor\b|\band\b', text):
        city = part.split(',', 1)[0].strip()
        city = re.sub(r'^greater\s+', '', city)
        city = re.sub(r'\s+area$', '', city)
        if city and city not in WILDCARD_LOCATIONS and city not in cities:
            cities.append(city)
    return cities


def _norm_location(text: str) -> str:
    """First city of the location string, '' if none (see _split_locations)."""
    cities = _split_locations(text)
    return cities[0] if cities else ''


def make_dedup_key(role: str, company: str, location: str) -> str:
    return f"{_norm(role)}|{_norm_company(company)}|{_norm_location(location)}"


# ── Cross-run dedup index ─────────────────────────────────────────────────────
# A job already in Notion contributes one key per city (a multi-city posting
# matches an incoming single-city one and vice versa), a "|@" presence marker
# for its title+company, and a "|*" wildcard key when its location is unknown.
# An incoming job is a duplicate iff:
#   - one of its cities collides with a stored city for the same title+company, or
#   - the stored posting had no real location ("|*"), or
#   - the incoming job has no real location and the title+company exists at all.
# Two postings with the same title+company in *different* real cities are NOT
# duplicates — each city stays a distinct key.

def make_index_keys(role: str, company: str, location: str) -> set[str]:
    """All dedup-index keys that a stored job contributes."""
    tc = f"{_norm(role)}|{_norm_company(company)}"
    cities = _split_locations(location)
    keys = {f"{tc}|{c}" for c in cities}
    keys.add(f"{tc}|@")
    if not cities:
        keys.add(f"{tc}|*")
    return keys


def match_existing(role: str, company: str, location: str,
                   index: set[str]) -> str | None:
    """Return the index key an incoming job collides with, or None if new."""
    tc = f"{_norm(role)}|{_norm_company(company)}"
    if f"{tc}|*" in index:
        return f"{tc}|*"
    cities = _split_locations(location)
    if not cities:
        return f"{tc}|@" if f"{tc}|@" in index else None
    for c in cities:
        if f"{tc}|{c}" in index:
            return f"{tc}|{c}"
    return None


def is_known_job(role: str, company: str, location: str,
                 index: set[str]) -> bool:
    return match_existing(role, company, location, index) is not None


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

    if not (_QUANT_TITLE_RE.search(title) or _PROGRAM_TITLE_RE.search(title)):
        return False, "EXCLUDED — no quant or new-grad program signal in title"

    noise = noise_hit(title)
    if noise:
        return False, f"EXCLUDED — non-quant function in title: '{noise}'"

    company_norm = _norm(company)
    if any(blocked in company_norm for blocked in COMPANY_BLOCKLIST):
        return False, f"EXCLUDED — company blocklist: '{company}'"

    senior_hit = _SENIOR_RE.search(title)
    if senior_hit:
        return False, f"EXCLUDED — senior signal in title: '{senior_hit.group()}'"

    intern_hit = _INTERN_RE.search(title)
    if intern_hit:
        return False, f"EXCLUDED — internship signal in title: '{intern_hit.group()}'"

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
    a _dedup_key column added.
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

    # NOTE: there used to be a second dedup on title+company ignoring location.
    # It silently dropped the same role in other cities (18% of passing rows in a
    # Nov 2026 sample, e.g. U.S. Bank Minneapolis vs Charlotte) — cities stay distinct.
    after_dedup = len(df)

    # Early-career filter (+ non-quant denylist). Track what the denylist removed.
    reasons = df.apply(filter_reason, axis=1)
    dropped = [
        f"{r.get('title','')} @ {r.get('company','')}"
        for (ok, why), (_, r) in zip(reasons, df.iterrows())
        if not ok and "non-quant function" in why
    ]
    keep = [ok for ok, _ in reasons]
    df = df[keep].copy()
    df.attrs["dropped_titles"] = dropped

    print(
        f"  Filters: {before} raw → {after_dedup} after dedup "
        f"→ {len(df)} after early-career filter"
        f"  ({len(dropped)} dropped as non-quant)"
    )
    return df
