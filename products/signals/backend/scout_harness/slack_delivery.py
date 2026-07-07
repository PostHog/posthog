"""Compose+send core for scout Slack alerts.

`send_scout_slack_notification` is the single path a scout finding takes to a Slack
channel: resolve the config's delivery target, best-effort tag the account owner,
compose the Block Kit alert, post it, and (when tied to a run) append the run's
audit entry. The `notify` viewset action wraps it with request validation; the
`simulate_scout_finding` management command calls it with `run=None` so developers
can exercise real channel delivery without a sandboxed LLM run.
"""

from __future__ import annotations

import dataclasses

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun

logger = structlog.get_logger(__name__)


def _escape_mrkdwn(text: str) -> str:
    """Slack mrkdwn control chars in customer-supplied strings; & first so we don't double-escape."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ScoutSlackDeliveryError(Exception):
    """Delivery failed before or at the Slack API. `code` mirrors the notify endpoint's
    error codes: `no_delivery_config`, `slack_integration_missing`, `channel_unavailable`."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclasses.dataclass(frozen=True)
class ScoutSlackDeliveryResult:
    # Display form, e.g. `#account-pulse` (falls back to the channel id).
    channel: str
    ts: str | None
    owner_tagged: bool


def send_scout_slack_notification(
    *,
    config: SignalScoutConfig,
    team_id: int,
    text: str,
    account_name: str,
    context_label: str,
    owner_email: str | None = None,
    owner_label: str | None = None,
    severity: str | None = None,
    report_id: str | None = None,
    run: SignalScoutRun | None = None,
) -> ScoutSlackDeliveryResult:
    """Post one scout alert to the config's Slack delivery channel.

    The destination always comes from `config.delivery_config["slack"]` — never from the
    caller. When `run` is given, the delivery is appended to `run.notifications` (the
    per-run audit the notify endpoint's cap counts against); with `run=None` no run
    state is touched. Raises `ScoutSlackDeliveryError` on any delivery failure.
    """
    delivery = (config.delivery_config or {}).get("slack") or {}
    if not delivery.get("integration_id") or not delivery.get("channel_id"):
        raise ScoutSlackDeliveryError(
            "This scout has no Slack delivery channel configured. Do not retry; note it in your run summary.",
            code="no_delivery_config",
        )

    integration = Integration.objects.filter(id=delivery["integration_id"], team_id=team_id, kind="slack").first()
    if integration is None:
        raise ScoutSlackDeliveryError(
            "The Slack integration behind this scout's delivery channel no longer exists. Do not retry.",
            code="slack_integration_missing",
        )
    slack = SlackIntegration(integration)

    owner_tagged = False
    # Escape customer/CRM-sourced strings so they can't inject Slack mentions/links; a server-built
    # `<@U…>` mention (set below) is the one owner_prefix value that must stay live.
    owner_prefix = _escape_mrkdwn(str(owner_label or ""))
    if owner_email:
        try:
            lookup = slack.client.users_lookupByEmail(email=owner_email)
            owner_slack_id = (lookup.get("user") or {}).get("id")
            if owner_slack_id:
                owner_prefix = f"<@{owner_slack_id}>"
                owner_tagged = True
        except Exception:
            # Tagging is best-effort — a lookup miss must never block delivery.
            logger.warning("scout_notify_owner_lookup_failed", exc_info=True)
        if not owner_tagged and not owner_prefix:
            owner_prefix = _escape_mrkdwn(str(owner_email))

    emoji = {"high": ":rotating_light:", "medium": ":warning:", "low": ":mag:"}.get(severity or "", ":mag:")
    safe_account_name = _escape_mrkdwn(account_name)
    safe_text = _escape_mrkdwn(text)
    body = f"{owner_prefix} {safe_text}".strip()
    context_text = context_label
    if report_id is not None:
        report_url = f"{settings.SITE_URL}/project/{team_id}/inbox/reports/{report_id}"
        context_text += f" · <{report_url}|View report in PostHog>"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji} *{safe_account_name}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context_text}]},
    ]

    try:
        posted = slack.client.chat_postMessage(
            channel=delivery["channel_id"],
            text=f"{safe_account_name}: {safe_text[:150]}",
            blocks=blocks,
            unfurl_links=False,
        )
    except SlackApiError as exc:
        slack_error = (getattr(exc, "response", None) or {}).get("error", "unknown_error")
        raise ScoutSlackDeliveryError(
            f"Slack rejected the delivery ({slack_error}) — the bot may have been removed from the "
            "channel. Mention this in your run summary and do not retry.",
            code="channel_unavailable",
        )

    ts = posted.get("ts")
    if run is not None:
        entry = {
            "channel_id": delivery["channel_id"],
            "ts": ts,
            "account_name": account_name,
            "owner_email": owner_email,
            "owner_tagged": owner_tagged,
            "report_id": report_id,
            "sent_at": timezone.now().isoformat(),
        }
        # Re-read the row under lock before appending: concurrent `notify` tool calls within one
        # run otherwise read the same `notifications` snapshot and the last save clobbers the
        # other's entry (and the endpoint's cap check). The lock serializes the append so no audit
        # entry is lost — the same pattern `scout_report/persistence._record_report_emit` uses.
        # (The message is already posted, so we never hold the lock across the Slack call.)
        with transaction.atomic():
            locked = SignalScoutRun.objects.select_for_update().get(pk=run.pk)
            locked.notifications = [*(locked.notifications or []), entry]
            locked.save(update_fields=["notifications"])

    return ScoutSlackDeliveryResult(
        channel=f"#{delivery.get('channel_name') or delivery['channel_id']}",
        ts=ts,
        owner_tagged=owner_tagged,
    )
