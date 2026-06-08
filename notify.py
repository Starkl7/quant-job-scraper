"""
notify.py — End-of-run Slack notifications.

Set SLACK_WEBHOOK_URL in .env or GitHub Secrets to enable.
All functions are best-effort — a Slack failure never breaks the main pipeline.

Create a webhook at: https://api.slack.com/messaging/webhooks
"""

import requests
from config import SLACK_WEBHOOK_URL


def send_slack(text: str) -> None:
    """Post a plain-text / mrkdwn message to the configured Slack channel."""
    if not SLACK_WEBHOOK_URL:
        return
    try:
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": text},
            timeout=8,
        )
        if resp.status_code != 200:
            print(f"  [Slack] Warning: {resp.status_code} — {resp.text[:80]}")
    except Exception as exc:
        print(f"  [Slack] Warning: {exc}")
