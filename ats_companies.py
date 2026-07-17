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

    # ── Quant Hedge Funds & Pod Shops ────────────────────────────────────────
    # Added Jun 2026 after vetting ~50 new firms; confirmed via live API tests.

    # Point72 — Academy internship programs (SG/HK/JP 2027); 2026 tech intern
    {"name": "Point72",                "ats": "greenhouse", "slug": "point72"},

    # QRT (Qube Research & Technologies) — 2026 Graduate + QR/Trading internships
    {"name": "Qube Research & Technologies", "ats": "greenhouse", "slug": "quberesearchandtechnologies"},

    # Schonfeld — 2026 BSc/MSc/PhD Quantitative Researcher Internship
    {"name": "Schonfeld",              "ats": "greenhouse", "slug": "schonfeld"},

    # Man Group — 2026 Technology Graduate Programme; QD/QR interns
    {"name": "Man Group",              "ats": "greenhouse", "slug": "mangroup"},

    # WorldQuant — Entry-Level Quantitative Strategist (Paris); Junior QA (Austin)
    {"name": "WorldQuant",             "ats": "greenhouse", "slug": "worldquant"},

    # AQR Capital — 2027 Summer Analyst programs: Research, Engineering, Risk
    {"name": "AQR Capital",            "ats": "greenhouse", "slug": "aqr"},

    # Squarepoint Capital — Graduate Quant Developer; Intern Software Dev Fall 2026
    {"name": "Squarepoint Capital",    "ats": "greenhouse", "slug": "squarepointcapital"},

    # Aquatic Capital — explicitly labels "Early Career" for QR and SWE; Intern QR Summer 2027
    {"name": "Aquatic Capital",        "ats": "greenhouse", "slug": "aquaticcapitalmanagement"},

    # Verition — quant-focused board; no grad program currently but worth monitoring
    {"name": "Verition",               "ats": "greenhouse", "slug": "veritiongroupllc"},

    # Acadian Asset Management — systematic quant; no grad listings currently
    {"name": "Acadian Asset Management", "ats": "greenhouse", "slug": "acadianassetmanagementllc"},

    # Graham Capital Management — systematic macro/quant; historically posts summer internships
    {"name": "Graham Capital Management", "ats": "greenhouse", "slug": "grahamcapitalmanagement"},

    # PDT Partners — quant HFT spinoff from Morgan Stanley; no early career currently
    {"name": "PDT Partners",           "ats": "greenhouse", "slug": "pdtpartners"},

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

    # ── Workday ───────────────────────────────────────────────────────────────
    # Endpoint: POST {tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    # Big banks that post 2027 new-grad / full-time analyst programs. All seven
    # endpoints live-verified Jul 2026. Descriptions aren't in the list API —
    # scoring's fetch_description backfills them. To add a Workday company:
    # open its careers search page, read the /wday/cxs/… request, and copy the
    # tenant, data-center (wdN), and site tokens here.

    {"name": "Citi",             "ats": "workday", "tenant": "citi",          "wd": "wd5", "site": "2"},
    {"name": "Morgan Stanley",   "ats": "workday", "tenant": "ms",            "wd": "wd5", "site": "External"},
    {"name": "Barclays",         "ats": "workday", "tenant": "barclays",      "wd": "wd3", "site": "External_Career_Site_Barclays"},
    {"name": "Deutsche Bank",    "ats": "workday", "tenant": "db",            "wd": "wd3", "site": "DBWebsite"},
    {"name": "TD Bank",          "ats": "workday", "tenant": "td",            "wd": "wd3", "site": "TD_Bank_Careers"},
    {"name": "State Street",     "ats": "workday", "tenant": "statestreet",   "wd": "wd1", "site": "Global"},
    {"name": "Northern Trust",   "ats": "workday", "tenant": "ntrs",          "wd": "wd1", "site": "northerntrust"},

    # ── Oracle Cloud Recruiting ────────────────────────────────────────────────
    # Endpoint: GET {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
    # Live-verified Jul 2026. Descriptions backfilled by scoring.

    {"name": "JPMorgan Chase", "ats": "oracle", "host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"},

    # ── Radancy (TalentBrew) ───────────────────────────────────────────────────
    # Endpoint: GET {url}/search-jobs/results (JSON envelope, HTML fragment inside)
    # Feed is NOT date-sorted — adapter pages the whole board and keeps recent.

    {"name": "Capital One", "ats": "radancy", "url": "https://www.capitalonecareers.com"},
]
