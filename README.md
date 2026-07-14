# Job Scraper

Automated pipeline that scrapes quantitative finance and finance-tech job listings from LinkedIn, Indeed, and Google Jobs, scores them with Gemini AI against your resume, and pushes results to a Notion database — runs daily on GitHub Actions.

## Overview

```
Scrapers (JobSpy / SerpAPI)
    ↓  deduplicate against Notion
Gemini Flash — batch score up to 10 jobs per call
    ↓  using resume PDFs as context
Gemma 4 31B — fetch missing descriptions (Google Search grounding)
    ↓  visa sponsorship detection
Notion — push scored listings
    ↓
Slack — daily summary (added / failed / re-scored / visa-denied)
```

## Pipelines

Three independent orchestrators run on separate schedules:

| Orchestrator | Source | Schedule (UTC) | Workflow |
|---|---|---|---|
| `run_jobspy.py` | LinkedIn + Indeed | 23:00 daily | `scrape.yml` |
| `run_serpapi.py` | Google Jobs | 02:00 daily | `score.yml` |
| `run_ats.py` | Direct company ATS endpoints | 04:00 and 16:00 | `ats.yml` |

All implement the same 4-phase pipeline:

1. **Startup** — validate Notion DB, initialize primary + backup Gemini clients, load resume PDFs, fetch existing Notion dedup keys
2. **Scrape → filter → dedup** — run queries, apply role/title filters, skip jobs already in Notion
3. **Score → push** — batch through Gemini (up to 10 jobs per call), push each to Notion; jobs scored without a description are queued for retry
4. **Low-confidence retry** — fetch missing descriptions via Gemma + Google Search grounding, re-score and update existing Notion pages; up to 2 retry attempts per job

## Roles Targeted

**JobSpy boolean search terms** (LinkedIn + Indeed):
- Quant researcher / analyst / strategist (excludes "developer")
- Quant trader / algorithmic trader / algo trader
- Quant risk analyst / market risk quant
- Quant developer / low-latency / HFT engineer / execution systems engineer
- Financial / quantitative data scientist / fintech data scientist
- Machine learning quant / ML quant / AI quant / deep learning quant

**SerpAPI search terms** (Google Jobs): Researcher, Trader, Risk, ModelRisk

Cities covered: 18 US metro areas across 54 JobSpy queries per run (3 role clusters × 18 cities), lookback window of 72 hours.

## AI Scoring

`scoring.py` sends jobs to **Gemini Flash** with your resume PDFs attached as binary context. Each batch call receives a prompt with up to 10 jobs and returns a JSON array:

```json
[
  {
    "job": 1,
    "fit_score": 8,
    "best_resume": "QR",
    "strengths": "...",
    "weaknesses": "...",
    "low_confidence": false,
    "visa_sponsored": true
  }
]
```

`fit_score` is clamped to [1–10]. `best_resume` defaults to `"QR"` if absent. `low_confidence: true` means the job was scored without a description.

### Visa Sponsorship Filtering

Jobs are filtered at three checkpoints using a strict three-state signal (`true` / `false` / `null`):

- `false` — job explicitly states no sponsorship ("will not sponsor", "must be authorized to work in the US", "US citizens and permanent residents only") → **dropped**
- `null` — sponsorship not mentioned → **kept** (silence is not denial)
- `true` — sponsorship confirmed → **kept**

Detection runs in two parallel channels:
1. **Gemma** appends `VISA: SPONSORED | NOT_SPONSORED | UNKNOWN` to the fetched description
2. **Gemini** returns a `visa_sponsored` field in its scoring JSON

Both orchestrators report `🚫 N visa-denied dropped` in the Slack summary.

### Quota Management

- Primary + backup Gemini clients on separate GCP projects; 429/RESOURCE_EXHAUSTED on primary auto-fails to backup
- 0.35s sleep between Notion pushes, 5s sleep between scoring batches (Gemini free-tier 15 RPM limit)
- 5s sleep between `fetch_description` calls

## Notion Schema

Scored jobs are pushed with these property keys (must match your Notion database exactly):

| Property | Type | Notes |
|---|---|---|
| `Fit Score-Dhrubo` | Number | 1–10 |
| `Best Resume-Dhrubo` | Select | e.g. `QR` |
| `AI Notes-Dhrubo` | Text | Strengths / weaknesses |
| `Source` | Select | LinkedIn, Indeed, Google Jobs |

## Project Structure

```
job-scraper/
├── run_jobspy.py          # LinkedIn + Indeed orchestrator
├── run_serpapi.py         # Google Jobs orchestrator
├── score_existing.py      # Local backfill — re-scores existing Notion entries
├── config.py              # All search constants, cities, query matrices
├── scoring.py             # Gemini batch scoring, Gemma description fetch, ScoreResult
├── notion.py              # push_job(), update_job_score()
├── filters.py             # Title/role filtering applied post-scrape
├── notify.py              # Slack webhook
├── scrapers/
│   ├── jobspy.py          # JobSpy (LinkedIn + Indeed) backend
│   ├── serpapi.py         # SerpAPI (Google Jobs) backend
│   └── ats.py             # Direct ATS endpoints (Greenhouse, Lever, …)
└── .github/workflows/
    ├── scrape.yml         # JobSpy daily run
    ├── score.yml          # SerpAPI daily run
    └── ats.yml            # ATS 12-hourly run
```

## Setup

### Dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` uses: `python-jobspy`, `pandas`, `requests`, `google-genai`, `python-dotenv`

### Environment Variables

Copy these into a `.env` file for local runs, or add as GitHub Actions secrets for CI:

| Variable | Required by | Description |
|---|---|---|
| `NOTION_TOKEN` | both | Notion integration token |
| `NOTION_DB_ID` | both | Target Notion database ID |
| `GEMINI_API_KEY` | both | Primary Gemini API key (GCP project 1) |
| `FETCH_DESCRIPTION_KEY` | both | Gemma API key (Gemini project with grounding access) |
| `RESUME_FOLDER_ID` | both | Google Drive folder ID containing resume PDFs |
| `SLACK_WEBHOOK_URL` | both | Incoming webhook for run summaries |
| `SERPAPI_KEY_1` | SerpAPI only | SerpAPI key for NY/Chicago city group |
| `SERPAPI_KEY_2` | SerpAPI only | SerpAPI key for Stamford/SF city group |

A second Gemini key can be set to enable backup quota failover (configured inside `scoring.py`).

### Running Locally

```bash
# LinkedIn + Indeed
python run_jobspy.py

# Google Jobs
python run_serpapi.py

# Direct company ATS endpoints
python run_ats.py

# Re-score existing Notion entries (backfill, no visa filter)
python score_existing.py
```

`run_serpapi.py` supports `SERPAPI_DRY_RUN=1` to test the pipeline without consuming SerpAPI credits.

## GitHub Actions

Both workflows trigger on a daily cron and support manual dispatch from the GitHub UI (`workflow_dispatch`). Timeout is set to 600 minutes.

To trigger manually: **Actions → [workflow name] → Run workflow**.
