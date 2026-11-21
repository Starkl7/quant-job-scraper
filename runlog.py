"""
runlog.py — Per-run health log for later checkups.

Each pipeline run builds one RunLog and appends a single JSON line to
<RUN_LOG_DIR>/run_health.jsonl (default: ./logs). The workflows upload that
file as an artifact and push it to the `run-logs` branch, because Actions
runners are wiped after every run.

Query a history, e.g.:
    jq -c '{p:.pipeline,t:.started,flags:.flags}' logs/run_health.jsonl
    jq -c 'select(.pipeline=="jobspy") | .scrape.failed_queries' logs/run_health.jsonl

Best-effort: logging must never break a pipeline run.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR  = Path(os.environ.get("RUN_LOG_DIR", "logs"))
LOG_FILE = "run_health.jsonl"

# A run is flagged when more than this share of scrape queries fail / come back empty.
QUERY_FAIL_ALERT_RATE = 0.20


class RunLog:
    def __init__(self, pipeline: str):
        self.pipeline   = pipeline
        self._t0        = time.time()
        self.started    = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.phases: dict[str, float]   = {}
        self.funnel: dict[str, int]     = {}
        self.counts: dict[str, int]     = {}
        self.queries: list[dict]        = []   # scrape queries (JobSpy / SerpAPI)
        self.sources: list[dict]        = []   # ATS endpoints
        self.dropped_titles: list[str]  = []   # titles removed by pre-LLM filters
        self.notes: list[str]           = []

    # ── recording ─────────────────────────────────────────────────────────────
    @contextmanager
    def phase(self, name: str):
        t = time.time()
        try:
            yield
        finally:
            self.phases[name] = round(time.time() - t, 1)

    def query(self, label: str, location: str, results: int, status: str,
              attempts: int = 1, errors: int = 0, error: str = "",
              seconds: float = 0.0) -> None:
        """status: ok | zero | partial_errors | timeout | exception"""
        self.queries.append({
            "label": label, "location": location, "results": results,
            "status": status, "attempts": attempts, "errors": errors,
            "error": error[:200], "seconds": round(seconds, 1),
        })

    def source(self, name: str, ats: str, listings: int, error: str = "") -> None:
        self.sources.append({"name": name, "ats": ats, "listings": listings,
                             "error": error[:200]})

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  [runlog] {text}")

    # ── derived health ────────────────────────────────────────────────────────
    def failed_queries(self) -> list[dict]:
        return [q for q in self.queries if q["status"] != "ok"]

    def flags(self) -> list[str]:
        out: list[str] = []
        if self.queries:
            bad = self.failed_queries()
            rate = len(bad) / len(self.queries)
            if rate > QUERY_FAIL_ALERT_RATE:
                out.append(f"{len(bad)}/{len(self.queries)} queries failed or empty "
                           f"({rate:.0%} > {QUERY_FAIL_ALERT_RATE:.0%})")
        dead = [s["name"] for s in self.sources if s["listings"] == 0]
        if dead:
            out.append(f"{len(dead)} ATS source(s) returned 0 listings: "
                       + ", ".join(dead[:12]) + ("…" if len(dead) > 12 else ""))
        return out

    def to_dict(self) -> dict:
        bad = self.failed_queries()
        return {
            "pipeline": self.pipeline,
            "started": self.started,
            "duration_s": round(time.time() - self._t0, 1),
            "phases_s": self.phases,
            "funnel": self.funnel,
            "counts": self.counts,
            "scrape": {
                "queries_total": len(self.queries),
                "queries_failed": len(bad),
                "failed_queries": [
                    f'{q["label"]} @ {q["location"]} [{q["status"]}, n={q["results"]}]'
                    for q in bad
                ],
                "queries": self.queries,
            },
            "ats_sources": {
                "total": len(self.sources),
                "zero_listing": [s["name"] for s in self.sources if s["listings"] == 0],
                "sources": self.sources,
            },
            "dropped_titles": self.dropped_titles[:200],
            "notes": self.notes,
            "flags": self.flags(),
        }

    def write(self) -> None:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(self.to_dict(), ensure_ascii=False) + "\n")
            flags = self.flags()
            print(f"\n  [runlog] appended to {LOG_DIR / LOG_FILE}"
                  + (f" — {len(flags)} health flag(s)" if flags else " — healthy"))
        except Exception as exc:   # never break the run over logging
            print(f"  [runlog] could not write run log: {exc}")

    def slack_flags_line(self) -> str:
        """One-line alert for the existing Slack summary; empty when healthy."""
        flags = self.flags()
        return ("⚠️ Health: " + "; ".join(flags)) if flags else ""
