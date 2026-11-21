"""
scrapers/wsc.py — wallstreetcareers.com (keyword search, server-rendered HTML).

Checked Nov 2026: robots.txt only disallows /rss/ (Crawl-delay: 1), listing pages are
plain HTML (20 cards/page, `q=` keyword, `order=posted_at`), and every detail page
carries a schema.org JobPosting JSON-LD block with the full description. We therefore
list cards with a polite >=1.2s delay and fetch descriptions only for net-new jobs
(see posting_fetch.py).

Returns rows in the shared schema, site="wallstreetcareers".
"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://www.wallstreetcareers.com"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
_DELAY    = 1.3          # robots.txt Crawl-delay is 1s
MAX_AGE_D = 7            # runs twice a day; a week of slack covers outages
MAX_PAGES = 5            # 100 newest cards per keyword is plenty at <=46 hits/keyword
KEYWORDS  = ["quant", "quantitative", "model validation", "model risk",
             "systematic", "trader", "strategist", "algorithmic"]

_AGE_RE   = re.compile(r"(\d+)\s*(h|d|w|m|y)", re.I)
_TITLE_A  = re.compile(r"^/jobs/\d+-")

NORMALIZED = ["title", "company", "location", "site", "job_url", "description",
              "min_amount", "max_amount", "job_type", "date_posted"]


def _age_days(text: str) -> int | None:
    m = _AGE_RE.search(text or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"h": 0, "d": n, "w": n * 7, "m": n * 30, "y": n * 365}[unit]


def _parse_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=_TITLE_A):
        href = a["href"]
        if href in seen:
            continue
        card = a
        for _ in range(12):                      # climb to the smallest wrapper with company + date
            card = card.parent
            if card is None:
                break
            hrefs = {x["href"] for x in card.find_all("a", href=_TITLE_A)}
            if len(hrefs) > 1:
                card = None
                break
            if card.find("a", href=re.compile(r"^/companies/")) and card.find(class_="job-posted-date"):
                break
        if card is None:
            continue
        seen.add(href)
        comp = card.find("a", href=re.compile(r"^/companies/"))
        loc  = card.find("a", href=re.compile(r"^/jobs/in-"))
        jt   = card.find("a", href=re.compile(r"^/jobs/(?:full|part)-time|^/jobs/contract", re.I))
        out.append({
            "title":    a.get_text(strip=True),
            "company":  comp.get_text(strip=True) if comp else "",
            "location": loc.get_text(strip=True) if loc else "",
            "job_type": jt.get_text(strip=True) if jt else "",
            "age":      _age_days(card.find(class_="job-posted-date").get_text(" ", strip=True)),
            "url":      BASE + href,
        })
    return out


def scrape_wsc(keywords: list[str] = KEYWORDS, runlog=None) -> pd.DataFrame:
    rows: dict[str, dict] = {}
    sess = requests.Session()
    sess.headers.update(_HEADERS)

    for kw in keywords:
        got, status, err = 0, "ok", ""
        for page in range(1, MAX_PAGES + 1):
            try:
                r = sess.get(f"{BASE}/jobs", params={"q": kw, "order": "posted_at", "page": page},
                             timeout=25)
                r.raise_for_status()
                cards = _parse_cards(r.text)
            except Exception as exc:
                status, err = "exception", f"{type(exc).__name__}: {exc}"
                print(f"  [WSC] '{kw}' p{page}: {err}")
                break
            time.sleep(_DELAY)
            if not cards:
                break
            stop = False
            for c in cards:
                if c["age"] is not None and c["age"] > MAX_AGE_D:
                    stop = True                  # newest-first → the rest are older
                    continue
                if c["url"] not in rows:
                    rows[c["url"]] = c
                got += 1
            if stop:
                break
        if status == "ok" and got == 0:
            status = "zero"
        print(f"  {got:>3} fresh — wallstreetcareers q={kw!r}")
        if runlog is not None:
            runlog.query(f"wsc:{kw}", "wallstreetcareers", got, status, error=err)

    if not rows:
        return pd.DataFrame(columns=NORMALIZED)
    recs = []
    for c in rows.values():
        age = c["age"] or 0
        recs.append({
            "title": c["title"], "company": c["company"], "location": c["location"],
            "site": "wallstreetcareers", "job_url": c["url"], "description": None,
            "min_amount": None, "max_amount": None, "job_type": c["job_type"],
            "date_posted": (date.today() - timedelta(days=age)).isoformat(),
        })
    return pd.DataFrame(recs, columns=NORMALIZED)
