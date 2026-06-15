"""
pipeline.py — Shared scoring + Notion push orchestration for scraper entry points.
"""

import time
from itertools import islice

import notion
from candidates import (
    Candidate,
    any_low_confidence,
    score_batch_all,
    score_single_all,
)
from config import SCORING_BATCH_SIZE
from scoring import fetch_description


def _chunked(iterable, n):
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


def score_and_push_jobs(
    jobs_list: list[dict],
    client,
    backup,
    resumes_by_candidate: dict[str, dict],
    candidates: list[Candidate],
) -> tuple[int, list, list, dict[str, int]]:
    """
    Score all jobs for every candidate and push to Notion.

    Returns (added_count, failed_push, low_conf_queue, source_counts).
    low_conf_queue items are (job, page_id).
    """
    added = 0
    failed_push = []
    low_conf_queue = []
    source_counts: dict[str, int] = {}

    for batch in _chunked(jobs_list, SCORING_BATCH_SIZE):
        scores_by_candidate = score_batch_all(
            batch, resumes_by_candidate, client,
            fetch_missing=True, backup_client=backup, candidates=candidates,
        )

        for job_idx, job in enumerate(batch):
            scores = {
                candidate.id: scores_by_candidate[candidate.id][job_idx]
                for candidate in candidates
            }
            page_id = notion.push_job(job, scores, candidates=candidates)
            if page_id:
                added += 1
                src = str(job.get("site", "other"))
                source_counts[src] = source_counts.get(src, 0) + 1
                if any_low_confidence(scores, job):
                    low_conf_queue.append((job, page_id))
            else:
                failed_push.append((job, scores))
            time.sleep(0.35)

        time.sleep(5)

    return added, failed_push, low_conf_queue, source_counts


def retry_low_confidence_jobs(
    low_conf_queue: list,
    client,
    backup,
    resumes_by_candidate: dict[str, dict],
    candidates: list[Candidate],
) -> int:
    """Fetch descriptions and re-score jobs that lacked one. Returns re_scored count."""
    re_scored = 0
    still_needs_desc = list(low_conf_queue)

    for retry_num in range(1, 3):
        if not still_needs_desc:
            break
        print(f"\n  ↺ Retry {retry_num}/2: {len(still_needs_desc)} job(s) still missing descriptions…")
        next_round = []
        for job, page_id in still_needs_desc:
            time.sleep(5)
            fetched = fetch_description(
                client, job.get("title", ""), job.get("company", ""),
                job.get("location", ""), backup_client=backup,
            )
            if not fetched:
                print(f"    → still no description: {job.get('title', '')[:40]}")
                next_round.append((job, page_id))
                continue
            job["description"] = fetched
            job["_fetched_chars"] = len(fetched)
            new_scores = score_single_all(
                job, resumes_by_candidate, client,
                backup_client=backup, candidates=candidates,
            )
            for score in new_scores.values():
                if score:
                    score.low_confidence = False
            if notion.update_job_score(page_id, new_scores, description=fetched, candidates=candidates):
                re_scored += 1
                primary = next(iter(new_scores.values()))
                fit = primary.fit_score if primary else "?"
                print(f"    ✓ re-scored {fit}/10 — {job.get('title', '')[:40]}")
        still_needs_desc = next_round

    return re_scored
