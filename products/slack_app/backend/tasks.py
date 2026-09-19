"""Celery tasks for the Slack app product."""

from celery import shared_task

from posthog.models.integration import Integration

from products.slack_app.backend.api import (
    SLACK_INTEGRATION_KIND,
    does_other_region_claim_workspace,
    send_region_proxy_request,
)
from products.slack_app.backend.services.slack_welcome_messages import send_install_welcome


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


@shared_task(ignore_result=True)
def send_slack_install_welcome(*, integration_id: int) -> None:
    """DM whoever installed the Slack app a welcome, dispatched from the install signal.

    Off the OAuth callback's request path because the installer is waiting on a redirect.
    No retries: a welcome that arrives late is worth less than a duplicate would cost, and
    the post is already best-effort inside ``send_install_welcome``.
    """
    integration = Integration.objects.filter(id=integration_id, kind=SLACK_INTEGRATION_KIND).first()
    if integration is None:
        return
    send_install_welcome(integration)
