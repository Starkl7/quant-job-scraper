# Job Scraper

Scrapes quant/trading roles from LinkedIn, Indeed, and Glassdoor daily via JobSpy and pushes net-new listings into a Notion database.

## What it does

- Runs every day at 9 AM UTC via GitHub Actions
- Queries for Quantitative Researcher, Trader, Analyst, Risk Analyst, and Quant Developer roles across US, UK, Singapore, and EU
- Deduplicates against your existing Notion entries (by Apply Link URL)
- Adds only new listings with Status = "To Apply"

---

## Setup (one-time)

### 1. Create a Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **New integration** → name it "Job Scraper" → Submit
3. Copy the **Internal Integration Secret** — this is your `NOTION_TOKEN`

### 2. Share the Notion database with the integration

1. Open the **Full-Time Job Applications** database in Notion
2. Click **...** (top right) → **Connections** → find "Job Scraper" → **Confirm**

### 3. Get the Database ID

Your database ID is:
```
353bbb22682242f3a3edbd574e0457b4
```
(already pre-filled in the secret below)

### 4. Create a GitHub private repo

```bash
git init
git add .
git commit -m "init job scraper"
gh repo create job-scraper --private --push --source=.
```

Or create a repo on github.com and push manually.

### 5. Add GitHub Secrets

In your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret name    | Value                                |
|----------------|--------------------------------------|
| `NOTION_TOKEN` | Your Notion integration secret       |
| `NOTION_DB_ID` | `353bbb22682242f3a3edbd574e0457b4`   |

### 6. Enable GitHub Actions

Go to **Actions** tab in your repo → click **Enable workflows**.

The scraper will run automatically every day. To trigger a manual run: **Actions** → **Daily Job Scraper** → **Run workflow**.

---

## Customizing queries

Edit the `QUERIES` list in `scrape.py`. Each entry is a tuple of:

```python
("search terms", "location", "country_indeed")
```

The `hours_old=48` parameter means each run only pulls jobs posted in the last 48 hours, so daily runs never miss a gap and never pull stale listings.

## Running locally

```bash
pip install -r requirements.txt
export NOTION_TOKEN="secret_..."
export NOTION_DB_ID="353bbb22682242f3a3edbd574e0457b4"
python scrape.py
```
