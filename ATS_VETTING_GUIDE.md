# ATS Vetting Guide — Adding New Companies

Reference for vetting a new prop trading firm before adding it to `ats_companies.py`.
Based on hands-on research across 65+ company websites.

---

## Workflow: vetting a new company in 5 steps

### Step 1 — Find the careers page
Visit the company's main website and locate their careers/jobs page. Common URLs:
- `company.com/careers`
- `company.com/jobs`
- `company.com/join-us`
- `careers.company.com`

### Step 2 — Identify the ATS
View page source and search for these keywords:

| Keyword in source | ATS |
|---|---|
| `greenhouse.io` | Greenhouse |
| `lever.co` | Lever |
| `ashbyhq.com` or `jobs.ashbyhq.com` | Ashby |
| `recruitee.com` | Recruitee |
| `workable.com` | Workable |
| `bamboohr.com` | BambooHR |
| `icims.com` or `jibecdn` | iCIMS (hard) |
| `workday.com` | Workday (hard) |
| `taleo` | Taleo (hard) |
| `paylocity.com` | Paylocity (hard) |
| `hibob.com` | HiBob (hard) |
| `nmbrshire.com` | Nmbrshire (hard, Israeli ATS) |
| `pinpointhq.com` or `jobs.json` on subdomain | Pinpoint |
| `monday.com/forms` | Monday.com forms (not a real ATS) |

If none match: check for iframes, `<script>` tags loading external job boards, or
redirects to a career subdomain. If the page is a plain WordPress/Wix site with no
embed, the company likely has no public ATS — **email-only** or LinkedIn-only.

### Step 3 — Find the slug
The slug/board token is the company-specific identifier within the ATS. Do not guess
from the company name — it is often different.

**Greenhouse:** search the page source for:
- `job-boards.greenhouse.io/embed/job_board?for=` → slug follows `for=`
- `gh_jid=` → the job ID, not the slug; the slug is in the board URL
- `boards.greenhouse.io/{slug}/` in any href
- If still unclear: try `boards-api.greenhouse.io/v1/boards/{guess}/jobs` with
  variations (company name, abbreviation, `companyname`, `companynameinc`)

**Lever:** search for `jobs.lever.co/{slug}/` in any link on the page.

**Ashby:** search for `jobs.ashbyhq.com/{slug}` in the page source.

**Recruitee:** look for `{slug}.recruitee.com` — the slug is the subdomain.

**Workable:** look for `apply.workable.com/{slug}/` in links.

**Pinpoint:** check if the career site domain has a `/jobs.json` endpoint — just
append `/jobs.json` to the careers subdomain URL.

### Step 4 — Test the endpoint programmatically
Run a quick Python one-liner to verify the endpoint returns real data:

```python
# Greenhouse
import requests
r = requests.get("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", timeout=10)
print(r.status_code, len(r.json().get("jobs", [])), "jobs")

# Lever
r = requests.get("https://api.lever.co/v0/postings/{slug}?mode=json", timeout=10)
print(r.status_code, len(r.json()), "jobs")

# Ashby
r = requests.get("https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=10)
print(r.status_code, len(r.json().get("jobs", [])), "jobs")

# Recruitee
r = requests.get("https://{slug}.recruitee.com/api/offers", timeout=10)
print(r.status_code, len(r.json().get("offers", [])), "jobs")

# Workable
r = requests.post("https://apply.workable.com/api/v3/accounts/{slug}/jobs",
    json={"query":"","location":[],"department":[],"worktype":[],"remote":[]}, timeout=10)
print(r.status_code, len(r.json().get("results", [])), "jobs")

# Pinpoint
r = requests.get("https://careers.{company}.com/jobs.json", timeout=10)
print(r.status_code, len(r.json().get("data", [])), "jobs")
```

**Expected responses:**
- `200` + job count > 0 → confirmed working
- `200` + job count = 0 → board exists but currently empty (still add it — it will activate)
- `404` → wrong slug, try variants
- `401` → wrong endpoint format (see gotchas below)
- `-1` / connection error → DNS issue or endpoint doesn't exist

### Step 5 — Audit job quality and add to config
Before adding, check a sample of the job titles. Look for:
- Is the board mixed (all levels) or targeted (grad-only, exp-only)?
- Are there noise listings (talent pools, events, competitions)?
- Does the company post separate boards for grad vs. experienced? If yes, consider
  adding both boards as separate entries.

Then add to `ats_companies.py` in the appropriate section.

---

## ATS system reference

### Greenhouse ✅ Easy
- **List endpoint:** `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
- **Response key:** `jobs` (list)
- **Fields:** `title`, `location.name`, `absolute_url`, `content` (HTML desc), `updated_at`
- **Description:** included via `?content=true` — full HTML, typically 1,000–15,000 chars
- **Notes:**
  - Use the US endpoint (`boards-api.greenhouse.io`) for ALL companies including
    European ones. The EU subdomain (`boards-api.eu.greenhouse.io`) has DNS
    resolution issues from some networks and is unnecessary — the US endpoint
    serves all boards.
  - Companies often have multiple boards: `{slug}` (lateral) + `{slug}campus` or
    `{slug}university` (grad). Check both.
  - The `job-boards.greenhouse.io` domain is for the human-facing embed; the
    `boards-api.greenhouse.io` domain is the machine-readable API. Use the latter.

### Lever ✅ Easy
- **List endpoint:** `GET https://api.lever.co/v0/postings/{slug}?mode=json&limit=100`
- **Response key:** root array
- **Fields:** `text` (title), `categories.location`, `hostedUrl`, `descriptionPlain`, `description`
- **Description:** `descriptionPlain` (preferred) or `description` (HTML fallback)
- **Notes:**
  - `mode=json` is required — omitting it returns HTML
  - `limit=100` prevents pagination (most boards have <100 listings)
  - `categories.allLocations` is a list when the role has multiple locations

### Ashby ✅ Easy
- **List endpoint:** `GET https://api.ashbyhq.com/posting-api/job-board/{slug}`
- **Response key:** `jobs` (list)
- **Fields:** `title`, `location`, `department`, `team`, `employmentType`, `publishedAt`
- **Description:** NOT included in the list endpoint — description requires a separate
  per-job call to `GET https://api.ashbyhq.com/posting-api/job-board/{slug}/job-postings/{id}`
- **Notes:**
  - The endpoint is `/posting-api/job-board/{slug}` — no `/jobs` suffix
  - Adding `/jobs` returns 401

### Recruitee ✅ Easy
- **List endpoint:** `GET https://{slug}.recruitee.com/api/offers`
- **Response key:** `offers` (list)
- **Fields:** `title`, `city`, `country`, `careers_url`, `description`, `created_at`
- **Description:** included in list response
- **Notes:**
  - The correct endpoint is the **subdomain** form: `{slug}.recruitee.com/api/offers`
  - The **centralized** form `api.recruitee.com/c/{slug}/positions` returns 401 — do not use

### Pinpoint ⚠️ Easy-Medium
- **List endpoint:** `GET https://{careers-domain}/jobs.json`
- **Response key:** `data` (list)
- **Fields:** `title`, `city`, `state`, `country_name`, `careers_url`, `description`, `benefits`
- **Description:** included but may be sparse
- **Notes:**
  - No standard slug — the full URL must be discovered from the company's career site
  - URL field (`careers_url`) is sometimes null in the feed; the apply link must be
    constructed as `{domain}/jobs/{id}-{title-slug}`
  - Wolverine Trading uses this at `careers.wolve.com/jobs.json`

### Workable ⚠️ Medium
- **List endpoint:** `POST https://apply.workable.com/api/v3/accounts/{slug}/jobs`
- **Request body:** `{"query":"","location":[],"department":[],"worktype":[],"remote":[]}`
- **Response key:** `results` (list)
- **Fields:** `title`, `city`, `country`, `url`, `description`, `published_on`
- **Description:** often not included in the list endpoint response; `url` also sometimes absent
- **Notes:**
  - Slug is the subdomain on `apply.workable.com/{slug}/` — visible in the job page URL
  - If `url` or `description` are missing, `fetch_description()` (Gemma) is the fallback
  - Some Workable accounts close without notice (Mandara disappeared — their
    `apply.workable.com/mandara-capital-careers/` redirected to `/oops` with no warning)

### BambooHR ⚠️ Medium
- **List endpoint:** `GET https://{slug}.bamboohr.com/careers/list`
- **Response:** JSON with `result` array
- **Notes:** less documented than Greenhouse/Lever; field names vary

### iCIMS ❌ Hard
- Uses **iCIMS Jibe** — AngularJS SPA. There is no unauthenticated JSON endpoint.
- The careers page renders client-side; HTTP GET returns the Angular shell, not jobs.
- Requires a headless browser or authenticated API access.
- SIG (Susquehanna) uses this. Skip unless headless browser support is added.

### Workday ❌ Hard
- Per-company REST endpoints exist (`{company}.wd5.myworkdayjobs.com/wday/cxs/...`)
  but the structure varies and most require CSRF tokens obtained via prior browser requests.
- Harder than iCIMS. Skip.

### Taleo / Oracle HCM ❌ Hard
- Legacy Oracle ATS. No consistent public API surface.
- Wolverine Trading previously used this before migrating to Pinpoint.

### Paylocity ❌ Hard
- Per-job GUID URLs, no discoverable list endpoint, JavaScript-rendered.
- XR Trading uses this. Skip.

### HiBob ❌ Hard
- Per-job GUID URLs at `{company}.careers.hibob.com`. No public list API.
- XY Capital uses this. Skip.

### Nmbrshire ❌ Hard
- Israeli ATS, per-job GUID URLs, no public list feed.
- Barak Capital uses this. Skip.

### Custom / Email-only ❌ Hard
- No ATS at all. Jobs posted on a WordPress or Wix page, or only through LinkedIn.
- Track manually or monitor LinkedIn via the existing JobSpy pipeline instead.
- Examples: Allston Trading, WH Trading, Grace Hall Trading, Genk Capital, Ora Traders.

---

## Common gotchas

### 1. The Greenhouse EU endpoint is a red herring
Agents and tools often report European companies use `boards-api.eu.greenhouse.io`.
In practice, **DNS resolution for that subdomain fails from many networks**. The
standard US endpoint `boards-api.greenhouse.io` works for every Greenhouse board
globally — use it unconditionally.

### 2. The Ashby endpoint has no `/jobs` suffix
`api.ashbyhq.com/posting-api/job-board/{slug}` → ✅ `200`
`api.ashbyhq.com/posting-api/job-board/{slug}/jobs` → ❌ `401`

### 3. Recruitee has two endpoints; only one is public
`{slug}.recruitee.com/api/offers` → ✅ `200`
`api.recruitee.com/c/{slug}/positions` → ❌ `401`

### 4. The Ashby `jump` slug is not Jump Trading
`jump` on Ashby belongs to a different entity (Jump Capital / Jump Crypto product org).
Jump Trading's real board is **Greenhouse `jumptrading`**. Always verify the slug
against the company's own careers page, not from third-party aggregators.

### 5. HRT's Greenhouse slug is `wehrtyou`
Hudson River Trading's slug is non-obvious. Cannot be guessed from the company name.
This is common — slugs like `drweng` (DRW) and `mavensecuritiesholdingltd` (Maven)
also don't match the visible brand name. Always discover from the page source.

### 6. Workable account deletions happen silently
When a company leaves Workable, their board URL redirects to `apply.workable.com/oops`
with no notice. Always test before assuming a previously-working slug still works.
Re-check the company's current careers page when this happens.

### 7. Some companies have multiple boards for the same ATS
Examples:
- **Chicago Trading Company** → `chicagotrading` (lateral) + `chicagotradingcampus` (grad)
- **Radix Trading** → `radixexperienced` + `radixuniversity`
- **Optiver** → `optiverus`, `optiverprivate`, `optiverneurips`, `tradingacademy2025`
- **DRW** → `drweng` may only surface engineering roles; check if other divisions post separately

Add each board as a separate entry in `ats_companies.py` under the same company name.
The dedup system handles any overlap.

### 8. Talent pools, events, and competitions look like job listings
ATS boards frequently include these non-job entries:
- "Join the X Talent Pool" / "X Talent Community" → NOT a role
- "2026 Quant Research Networking Event" → NOT a role (VIRTU)
- "Virtual Quant Trading Challenge" → NOT a role (Akuna)
- "General Interest - Campus / Experienced Hires" → NOT a specific role
- "Expression of Interest" (generic, no role title) → NOT a role (Epoch)
- **BUT:** "Options Trader - Expression of Interest" (Eclipse) → IS worth tracking;
  role-specific EOIs signal active hiring intent

The `_is_noise()` function in `scrapers/ats.py` catches the common cases. If a new
noise pattern appears, add it to `_NOISE_PHRASES` there.

### 9. "Event" is too broad as a noise keyword
"Senior Events Coordinator" and "Macro Analyst - Event Driven" both contain "event"
but are real roles. Only use multi-word phrases: `"networking event"`, `"talent pool"`.

### 10. Graduation deadlines live in descriptions, not titles
Roles with "Graduate" in the title can still be ineligible: DV Trading's "2026 Graduate
Trader" requires graduating by Summer 2026. The `_GRAD_CUTOFF_RE` regex in `run_ats.py`
catches these from description text. When adding a new company, check whether their
graduate roles have explicit graduation windows in the description.

### 11. Some firms post "unlabelled" roles that are actually for experienced hires
The ATS pipeline requires an **explicit early-career signal** in the title
(junior / graduate / campus / class-year / associate / launchpad / master's / bachelor's).
Unlabelled "Quantitative Researcher" or "Trader" on an ATS board is almost certainly
experienced — unlike job board searches (LinkedIn/Indeed) where these might be entry-level.
This is by design: the JobSpy/SerpAPI pipelines already surface unlabelled roles.

### 12. Verify real job count vs. raw count
A board returning 200 jobs is not automatically useful. Check:
- How many are real, specific roles (vs. events/pools/EOIs)?
- Are most explicitly "experienced" (already filtered) or mixed-level?
- Are there any early-career roles at all, or does this company not label them?
  If they never label grad roles explicitly, adding the board will yield 0 results
  after filtering and is not worth tracking via ATS (use JobSpy instead).

### 13. Two companies can share a name fragment in a slug
Always validate the slug produces the expected company name and role titles in the
API response. A 200 response from a mismatched slug wastes Gemini quota on
irrelevant jobs.

---

## Adding a company to ats_companies.py

Once verified, add an entry to the appropriate section:

```python
# Greenhouse
{"name": "Company Name",  "ats": "greenhouse", "slug": "discovered-slug"},

# Lever
{"name": "Company Name",  "ats": "lever",      "slug": "discovered-slug"},

# Recruitee
{"name": "Company Name",  "ats": "recruitee",  "slug": "discovered-slug"},

# Pinpoint (full URL required)
{"name": "Company Name",  "ats": "pinpoint",   "url": "https://careers.company.com/jobs.json"},

# Workable
{"name": "Company Name",  "ats": "workable",   "slug": "discovered-slug"},
```

Then run `probe_ats.py` (or the one-liner in Step 4) to confirm the endpoint is live.
No code changes needed to `run_ats.py` or `scrapers/ats.py` for supported ATS types.

---

## Hard-to-track companies and alternatives

These firms were researched but are impractical to scrape directly. Use the
JobSpy/SerpAPI pipelines or monitor LinkedIn manually instead.

| Company | ATS | Why hard | Alternative |
|---|---|---|---|
| Citadel Securities | Custom (403) | Blocks all scrapers; no public ATS | LinkedIn via JobSpy |
| SIG (Susquehanna) | iCIMS Jibe | AngularJS SPA, no JSON endpoint | LinkedIn via JobSpy |
| Allston Trading | Unknown | No public ATS found | LinkedIn via JobSpy |
| WH Trading | Email only | `opportunities@whtrading.com` | N/A |
| Grace Hall Trading | None | 2–10 person boutique, referral-only | N/A |
| XR Trading | Paylocity | Per-job GUIDs, no list feed | LinkedIn via JobSpy |
| XY Capital | HiBob | Per-job GUIDs, no list feed | LinkedIn via JobSpy |
| Barak Capital | Nmbrshire | Niche ATS, per-job GUIDs | N/A |
| Quadeye | Custom WP | WordPress site, no ATS embed | LinkedIn via JobSpy |
| Mandara | (Workable closed) | Account deleted, redirects to /oops | Re-check periodically |
| WMC | Not found | No prop trading firm identified at this name | Verify firm name |
| Genk Capital | Custom portal | `join.genkcapital.com` assessment portal | N/A |
| North Pool | Custom | Amsterdam energy firm (may not be prop trading) | Verify entity |
