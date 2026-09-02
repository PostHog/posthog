from dataclasses import asdict
from typing import Any

from django.conf import settings

import requests

from posthog.cloud_utils import is_cloud
from posthog.utils import compact_number

DIGEST_WEBHOOK_TIMEOUT_SECONDS = 10

# Webhook trigger of the "[Error tracking] Weekly digest email" workflow in the internal
# PostHog project. Protected by WORKFLOWS_WEBHOOK_SECRET, so the URL is not a secret.
DIGEST_WORKFLOW_WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/019f2754-aeff-0000-6a0d-5d3933a94b08"


def build_team_section_payload(data: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe project section for the digest workflow webhook payload.

    Big counts are pre-formatted here because the email template (Liquid) has no
    number formatting filter. ingestion_failure_count must stay numeric — the
    template branches on `> 0` — so it gets a display twin instead. Copies, not
    in-place mutation: the same data dict is reused across recipients.
    """

    def serialize_issue(issue: dict[str, Any]) -> dict[str, Any]:
        return {**issue, "id": str(issue["id"]), "occurrence_count": compact_number(issue["occurrence_count"])}

    section = {k: v for k, v in data.items() if k != "team"}
    section["team_name"] = data["team"].name
    section["exception_count"] = compact_number(data["exception_count"])
    section["ingestion_failure_count_display"] = compact_number(data["ingestion_failure_count"])
    crash_free = data["crash_free"]
    # The digest webhook payload represents "no crash-free data" as {}, not null
    section["crash_free"] = (
        {**asdict(crash_free), "total_sessions": compact_number(crash_free.total_sessions)} if crash_free else {}
    )
    section["top_issues"] = [serialize_issue(i) for i in data["top_issues"]]
    section["new_issues"] = [serialize_issue(i) for i in data["new_issues"]]
    return section


def send_digest_to_workflow(digest: dict[str, Any], distinct_id: str) -> None:
    """POST one recipient's digest to the delivery workflow's webhook trigger.

    Raises on failure so callers (celery autoretry) can retry.
    """
    # Single choke point where digest data leaves the instance, so the cloud-only guarantee is
    # enforced here rather than in each caller.
    if not is_cloud():
        raise RuntimeError("Error Tracking weekly digest cannot send from a self-hosted deployment")

    headers = {}
    if settings.WORKFLOWS_WEBHOOK_SECRET:
        headers["Authorization"] = settings.WORKFLOWS_WEBHOOK_SECRET

    response = requests.post(
        DIGEST_WORKFLOW_WEBHOOK_URL,
        json={
            "event": "error_tracking_weekly_digest",
            "distinct_id": distinct_id,
            "digest": digest,
        },
        headers=headers,
        timeout=DIGEST_WEBHOOK_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
