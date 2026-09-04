"""Celery tasks for the Slack app product."""

import uuid

from celery import shared_task

from posthog.models.integration import Integration
from posthog.models.user import User

from products.slack_app.backend.api import (
    ERROR_TRACKING_RESOLVE_ACTION_ID,
    SLACK_INTEGRATION_KIND,
    does_other_region_claim_workspace,
    send_region_proxy_request,
)
from products.slack_app.backend.services import inbox_interactivity


@shared_task(ignore_result=True)
def mirror_slack_message_event(
    *, slack_team_id: str, incoming_host: str, target_url: str, headers: dict[str, str], body: str
) -> None:
    """Deliver an emit-only mirror of a channel message to the other region.

    Runs out of band so the Slack webhook acks within its budget instead of waiting on the claims
    probe and the cross-region POST. No retries: the receiver rejects Slack timestamps older than
    five minutes, and a lost mirror costs the other region one message, which the caller accepts.
    """
    claimed = does_other_region_claim_workspace(
        slack_team_id=slack_team_id,
        kinds=[SLACK_INTEGRATION_KIND],
        incoming_host=incoming_host,
    )
    if not claimed:
        return
    # The body rides as text because Celery serializes arguments to JSON. Slack signs the raw
    # bytes, and the payload is UTF-8 JSON, so the decode/encode round trip is byte-exact.
    send_region_proxy_request(method="POST", target_url=target_url, headers=headers, body=body.encode("utf-8"))


@shared_task(ignore_result=True, max_retries=0)
def run_error_tracking_issue_action(
    *, action_id: str, issue_id: str, fingerprint: str | None, integration_id: int, user_id: int, response_url: str
) -> None:
    """Apply a Resolve / Assign to me click from an alert thread and tell the clicker the outcome.

    The interactivity callback has already verified the workspace owns the integration and
    resolved the clicker to an org member; the error tracking facade re-derives project access
    from the issue row. Runs out of band so the callback acks Slack within its budget.
    """
    from products.error_tracking.backend.facade.issues import (  # noqa: PLC0415 — cross-product calls kept off the slack import path
        assign_issue_to_user_from_slack,
        resolve_issue_from_slack,
    )

    integration = Integration.objects.filter(
        id=integration_id, kind=SLACK_INTEGRATION_KIND
    ).first()  # nosemgrep: idor-lookup-without-team
    user = User.objects.filter(id=user_id, is_active=True).first()
    if integration is None or user is None:
        return

    if action_id == ERROR_TRACKING_RESOLVE_ACTION_ID:
        outcome = resolve_issue_from_slack(
            uuid.UUID(issue_id), fingerprint=fingerprint, integration=integration, user=user
        )
        texts = {"ok": "Resolved. The thread will update in a moment.", "already": "This issue is already resolved."}
    else:
        outcome = assign_issue_to_user_from_slack(
            uuid.UUID(issue_id), fingerprint=fingerprint, integration=integration, user=user
        )
        texts = {
            "ok": "Assigned to you. The thread will update in a moment.",
            "already": "This issue is already assigned to you.",
        }
    if outcome == "not_found":
        text = "This issue no longer exists in PostHog."
    elif outcome == "no_access":
        text = "You do not have access to change this issue in PostHog."
    else:
        text = texts[outcome]
    inbox_interactivity.post_response_url(
        response_url, {"response_type": "ephemeral", "replace_original": False, "text": text}
    )
