#!/usr/bin/env bash
# Append this run's logs/run_health.jsonl to the `run-logs` branch so history
# survives the ephemeral Actions runner. Best-effort: never fails the workflow.
set -uo pipefail

SRC="logs/run_health.jsonl"
[ -f "$SRC" ] || { echo "no $SRC — nothing to push"; exit 0; }

TMP="${RUNNER_TEMP:-/tmp}/run_health_new.jsonl"
cp "$SRC" "$TMP"

git config user.name  "run-log-bot"
git config user.email "run-log-bot@users.noreply.github.com"

for attempt in 1 2 3 4; do
  if git fetch --quiet origin run-logs 2>/dev/null; then
    git checkout --quiet -B run-logs origin/run-logs
  else
    git checkout --quiet --orphan run-logs
    git rm -rf --quiet . 2>/dev/null || true
  fi
  cat "$TMP" >> run_health.jsonl
  git add run_health.jsonl
  git commit --quiet -m "run log: ${GITHUB_WORKFLOW:-local} #${GITHUB_RUN_ID:-0}" || exit 0
  if git push --quiet origin run-logs; then
    echo "run log pushed to run-logs (attempt $attempt)"
    exit 0
  fi
  echo "push raced with another workflow — retrying ($attempt/4)"
  sleep $((attempt * 3))
done
echo "could not push run log (artifact upload still has it)"
exit 0
