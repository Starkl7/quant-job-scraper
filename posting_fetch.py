"""
posting_fetch.py — Fetch the REAL job-posting text for net-new jobs.

JobSpy runs with linkedin_fetch_description=False (a detail-page request per
result is too slow across ~2k rows), so every LinkedIn job arrives with no
description. We instead fetch descriptions only for the handful of *net-new*
jobs (≈20-50/run), via LinkedIn's public guest endpoint, with polite delays.

Circuit breaker: after MAX_CONSECUTIVE_FAILS failures in a row (429 / authwall /
network), fetching is disabled for the rest of the run and jobs fall back to
title/company scoring (flagged low-confidence). Never raises.
"""

from __future__ import annotations

import os
import random
import re
import time

import requests

ENABLE_POSTING_FETCH   = os.environ.get("ENABLE_POSTING_FETCH", "true").lower() == "true"
MAX_FETCHES_PER_RUN    = int(os.environ.get("POSTING_FETCH_CAP", "150"))
MAX_CONSECUTIVE_FAILS  = 3
MIN_CHARS              = 150

_LI_ID_RE = re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*?-)?(\d{6,})")
_GUEST    = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
_HEADERS  = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_text(html_text: str) -> str:
    from bs4 import BeautifulSoup   # jobspy dependency, so already installed
    soup = BeautifulSoup(html_text, "html.parser")
    node = soup.select_one("div.show-more-less-html__markup") or soup.select_one(".description__text")
    if not node:
        return ""
    for br in node.find_all("br"):
        br.replace_with("\n")
    text = node.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


class PostingFetcher:
    def __init__(self):
        self.attempts = 0
        self.successes = 0
        self.consecutive_fails = 0
        self.disabled_reason = "" if ENABLE_POSTING_FETCH else "ENABLE_POSTING_FETCH=false"
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    @property
    def active(self) -> bool:
        return not self.disabled_reason

    def stats(self) -> dict:
        return {"attempts": self.attempts, "successes": self.successes,
                "disabled": self.disabled_reason}

    def fetch(self, job_url: str) -> str:
        """Return posting text, or '' (unsupported URL, blocked, or not found)."""
        if not self.active:
            return ""
        m = _LI_ID_RE.search(job_url or "")
        if not m:
            return ""                      # non-LinkedIn URL: nothing to do here
        if self.attempts >= MAX_FETCHES_PER_RUN:
            self.disabled_reason = f"per-run cap {MAX_FETCHES_PER_RUN} reached"
            return ""

        self.attempts += 1
        time.sleep(random.uniform(1.5, 3.5))
        try:
            r = self.session.get(_GUEST.format(id=m.group(1)), timeout=20)
            if r.status_code == 429:       # one patient retry before counting a failure
                time.sleep(random.uniform(12, 20))
                r = self.session.get(_GUEST.format(id=m.group(1)), timeout=20)
            if r.status_code in (429, 999) or r.status_code >= 500 or "authwall" in r.url:
                raise RuntimeError(f"HTTP {r.status_code}")
            if r.status_code != 200:
                return ""                  # e.g. 404 (posting closed) — not a throttle signal
            text = _extract_text(r.text)
        except Exception as exc:
            self.consecutive_fails += 1
            print(f"      ⚠ posting fetch failed ({str(exc)[:60]}) "
                  f"[{self.consecutive_fails}/{MAX_CONSECUTIVE_FAILS}]")
            if self.consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                self.disabled_reason = "circuit breaker: repeated failures/throttling"
                print(f"      ✗ posting fetch disabled for this run ({self.disabled_reason})")
            return ""

        self.consecutive_fails = 0
        if len(text) < MIN_CHARS:
            return ""
        self.successes += 1
        return text


# Shared per-process instance (one run = one process)
fetcher = PostingFetcher()
