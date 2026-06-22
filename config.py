"""
config.py — Single source of truth for all constants.
No logic, no I/O. Import from here everywhere else.
"""

import os

# ── Secrets (from environment / .env) ─────────────────────────────────────────

NOTION_TOKEN     = os.environ.get("NOTION_TOKEN",      "")
NOTION_DB_ID     = os.environ.get("NOTION_DB_ID",      "")
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY",    "")
RESUME_FOLDER_ID = os.environ.get("RESUME_FOLDER_ID",  "")
SERPAPI_KEY_1    = os.environ.get("SERPAPI_KEY_1",      "")
SERPAPI_KEY_2    = os.environ.get("SERPAPI_KEY_2",      "")

# Second Gemini key — MUST be from a different Google project/account to give
# independent quota. Falls back to FETCH_DESCRIPTION_KEY if GEMINI_API_KEY_2
# is not explicitly set (backward-compat for existing .env files).
GEMINI_API_KEY_2 = os.environ.get(
    "GEMINI_API_KEY_2",
    os.environ.get("FETCH_DESCRIPTION_KEY", ""),
)

# Slack webhook for end-of-run summary (optional). Leave blank to disable.
# Create a webhook at: https://api.slack.com/messaging/webhooks
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# Dry-run guard: when True, SerpAPI scrape_all() logs what it WOULD search but
# makes no actual API calls — preserves monthly credits during workflow testing.
# Activate with: SERPAPI_DRY_RUN=true python run_serpapi.py
SERPAPI_DRY_RUN = os.environ.get("SERPAPI_DRY_RUN", "false").lower() == "true"

# ── LLM ───────────────────────────────────────────────────────────────────────

# Gemini 3.1 Flash Lite — free tier: 15 RPM, 250k tokens/min, 500 RPD.
# Verify the exact model ID in AI Studio (aistudio.google.com) and update here.
SCORING_MODEL             = "models/gemini-3.1-flash-lite"  # 15 RPM, 250k TPM, 500 RPD — PDF + batch scoring
FETCH_DESCRIPTION_MODEL   = "gemma-4-31b-it"                # 15 RPM, unlimited TPM, 1.5k RPD — separate quota
SCORING_BATCH_SIZE        = 10

# ── Notion ────────────────────────────────────────────────────────────────────

NOTION_API_VERSION = "2022-06-28"
RESUME_LABELS      = ("QT", "QR", "QA", "Risk")

SOURCE_MAP = {
    "linkedin": "LinkedIn",
    "indeed":   "Indeed",
    "google":   "Google Jobs",
    "ats":      "ATS",
}

# ── JobSpy search terms (LinkedIn + Indeed) ────────────────────────────────────
# Complex boolean expressions — JobSpy passes these verbatim to each board.

RESEARCHER_TERM = (
    '("quantitative researcher" OR "quant researcher" OR "quantitative analyst" '
    'OR "quant analyst" OR "quantitative strategist" OR "quant strategist") -developer'
)
TRADER_TERM = (
    '("quantitative trader" OR "quant trader" OR "algorithmic trader" OR "algo trader")'
)
RISK_TERM = (
    '("quantitative risk analyst" OR "quant risk analyst" OR "risk quant" '
    'OR "market risk quant" OR "quant risk") -developer'
)
# ── SerpAPI search terms (Google Jobs) ────────────────────────────────────────
# Simple OR chains — complex parenthesised boolean causes zero-result errors
# on Google Jobs when combined with date filters.

GJ_TERMS: dict[str, str] = {
    "Researcher": (
        "quantitative researcher OR quant researcher OR quant analyst"
        " OR quantitative analyst OR quantitative strategist"
    ),
    "Trader": (
        "quantitative trader OR quant trader OR algorithmic trader OR algo trader"
    ),
    "Risk": (
        "quantitative risk analyst OR quant risk analyst OR market risk quant"
    ),
    "ModelRisk": (
        "model risk analyst OR model validation analyst OR model risk associate"
        " OR quantitative model validator OR model validation associate"
    ),
}

SERPAPI_DATE_FILTER = "date_posted:today"   # rolling 24-hour window

# Key 1 handles high-volume US hubs; Key 2 handles hedge-fund corridor + West Coast.
SERPAPI_KEY_GROUPS: list[dict] = [
    {"key_env": "SERPAPI_KEY_1", "cities": ["New York, NY",          "Chicago, IL"]},
    {"key_env": "SERPAPI_KEY_2", "cities": ["Stamford, Connecticut", "San Francisco, California"]},
]

# ── City lists (JobSpy) ────────────────────────────────────────────────────────

US_CITIES: list[tuple[str, str]] = [
    ("New York, NY",       "USA"),   # Wall Street, hedge funds, bulge brackets
    ("Chicago, IL",        "USA"),   # Citadel, DRW, Jump, Virtu, CME
    ("San Francisco, CA",  "USA"),   # tech-adjacent quant, fintech
    ("Boston, MA",         "USA"),   # Fidelity, State Street, Two Sigma office
    ("Stamford, CT",       "USA"),   # Bridgewater, AQR, Point72, hedge fund corridor
    ("Jersey City, NJ",    "USA"),   # Goldman, JPMorgan, bank back-offices
    ("Austin, TX",         "USA"),   # Citadel, Jane Street expansion hub
    ("Los Angeles, CA",    "USA"),   # hedge funds, Western Asset, Ares
    ("Seattle, WA",        "USA"),   # tech-quant crossover, DE Shaw, Amazon
    ("Miami, FL",          "USA"),   # growing finance hub, Citadel HQ
    ("Charlotte, NC",      "USA"),   # Bank of America, Wells Fargo
]

INTL_CITIES: list[tuple[str, str]] = [
    ("London, United Kingdom", "UK"),
    ("Hong Kong",              "Hong Kong"),
    ("Singapore",              "Singapore"),
    ("Zurich, Switzerland",    "Switzerland"),
    ("Amsterdam, Netherlands", "Netherlands"),
    ("Toronto, Canada",        "Canada"),
    ("Sydney, Australia",      "Australia"),
]

ALL_CITIES = US_CITIES + INTL_CITIES

# 3 role clusters × 18 cities = 54 queries per JobSpy run.
# Each tuple: (search_term, location, country_indeed)
JOBSPY_QUERIES: list[tuple[str, str, str]] = [
    (term, loc, country)
    for term in (RESEARCHER_TERM, TRADER_TERM, RISK_TERM)
    for loc, country in ALL_CITIES
]

# ── JobSpy scrape parameters ──────────────────────────────────────────────────

JOBSPY_RESULTS_WANTED = 200
JOBSPY_HOURS_OLD      = 72
