"""
ats_companies.py — Registry of company ATS endpoints to monitor.

Each entry:
  name  — display name written to Notion "Company" field
  ats   — one of: greenhouse | lever | recruitee | pinpoint | workable
  slug  — board token/slug (greenhouse, lever, recruitee, workable)
  url   — full endpoint URL (pinpoint only)

To add a company: append an entry and re-deploy.
To pause a company: comment out or delete its entry.
"""

COMPANIES: list[dict] = [

    # ── Greenhouse ────────────────────────────────────────────────────────────
    # Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

    {"name": "Jane Street",             "ats": "greenhouse", "slug": "janestreet"},
    {"name": "Jump Trading",            "ats": "greenhouse", "slug": "jumptrading"},
    {"name": "Optiver",                 "ats": "greenhouse", "slug": "optiverus"},
    {"name": "DRW",                     "ats": "greenhouse", "slug": "drweng"},
    {"name": "Flow Traders",            "ats": "greenhouse", "slug": "flowtraders"},
    {"name": "Hudson River Trading",    "ats": "greenhouse", "slug": "wehrtyou"},
    {"name": "Akuna Capital",           "ats": "greenhouse", "slug": "akunacapital"},
    {"name": "VIRTU Financial",         "ats": "greenhouse", "slug": "virtu"},
    {"name": "Tower Research Capital",  "ats": "greenhouse", "slug": "towerresearchcapital"},
    {"name": "XTX Markets",             "ats": "greenhouse", "slug": "xtxmarketstechnologies"},
    {"name": "3Red Partners",           "ats": "greenhouse", "slug": "3redpartners"},
    {"name": "BlackEdge Capital",       "ats": "greenhouse", "slug": "blackedgecapital"},
    {"name": "Chicago Trading Company", "ats": "greenhouse", "slug": "chicagotrading"},
    {"name": "Chicago Trading Company", "ats": "greenhouse", "slug": "chicagotradingcampus"},
    {"name": "DV Trading",              "ats": "greenhouse", "slug": "dvtrading"},
    {"name": "Five Rings Capital",      "ats": "greenhouse", "slug": "fiveringsllc"},
    {"name": "Gelber Group",            "ats": "greenhouse", "slug": "gelbergroup"},
    {"name": "Geneva Trading",          "ats": "greenhouse", "slug": "genevatrading"},
    {"name": "Headlands Technologies",  "ats": "greenhouse", "slug": "headlandstechnologiesllc"},
    {"name": "Old Mission Capital",     "ats": "greenhouse", "slug": "oldmissioncapital"},
    {"name": "Radix Trading",           "ats": "greenhouse", "slug": "radixexperienced"},
    {"name": "Radix Trading",           "ats": "greenhouse", "slug": "radixuniversity"},
    {"name": "TransMarket Group",       "ats": "greenhouse", "slug": "transmarketgroup"},
    {"name": "Da Vinci Trading",        "ats": "greenhouse", "slug": "davinciderivatives"},
    {"name": "Mako",                    "ats": "greenhouse", "slug": "mako"},
    {"name": "Maven Securities",        "ats": "greenhouse", "slug": "mavensecuritiesholdingltd"},
    {"name": "Maverick Derivatives",    "ats": "greenhouse", "slug": "maverickderivatives"},
    {"name": "VivCourt Trading",        "ats": "greenhouse", "slug": "vivcourtevents"},
    {"name": "Epoch",                   "ats": "greenhouse", "slug": "epochcapital"},
    {"name": "AlphaGrep",               "ats": "greenhouse", "slug": "alphagrepsecurities"},
    {"name": "Eclipse Trading",         "ats": "greenhouse", "slug": "eclipsetrading"},
    {"name": "Graviton",                "ats": "greenhouse", "slug": "gravitonresearchcapital"},
    {"name": "Grasshopper",             "ats": "greenhouse", "slug": "grasshopperasia"},
    {"name": "IMC Trading",             "ats": "greenhouse", "slug": "imc"},
    {"name": "NK Securities",           "ats": "greenhouse", "slug": "nksecuritiesresearch"},
    {"name": "Quantbox Research",       "ats": "greenhouse", "slug": "quantboxresearchpte"},

    # ── Lever ─────────────────────────────────────────────────────────────────
    # Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json

    {"name": "Belvedere Trading",  "ats": "lever", "slug": "belvederetrading"},
    {"name": "HAP Capital",        "ats": "lever", "slug": "hap-capital"},
    {"name": "Valkyrie Trading",   "ats": "lever", "slug": "valkyrietrading"},

    # ── Recruitee ─────────────────────────────────────────────────────────────
    # Endpoint: https://{slug}.recruitee.com/api/offers

    {"name": "Mathrix",       "ats": "recruitee", "slug": "mathrix"},
    {"name": "WEBB Traders",  "ats": "recruitee", "slug": "webbtraders"},

    # ── Pinpoint ──────────────────────────────────────────────────────────────
    # Endpoint: full URL provided (jobs.json feed)

    {"name": "Wolverine Trading", "ats": "pinpoint", "url": "https://careers.wolve.com/jobs.json"},

    # ── Workable ──────────────────────────────────────────────────────────────
    # Endpoint: POST https://apply.workable.com/api/v3/accounts/{slug}/jobs

    {"name": "Eagle Seven", "ats": "workable", "slug": "eagle-seven"},
]
