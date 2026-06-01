"""Slack notifications for signals inbox items.

When a report transitions to READY (a new inbox item lands), we look up the
suggested reviewers from its `suggested_reviewers` artefact, resolve them to
PostHog users, and dispatch a Slack message for each user that has configured a
Slack channel and integration in their `SignalUserAutonomyConfig`.

Reviewers are grouped by their resolved Slack channel so each channel receives a
single message — when several reviewers point at the same channel, that one
message tags all of them rather than posting once per reviewer.

Each user's `slack_notification_min_priority` filters out reports below the
configured threshold (P0 is highest). When the report has no priority
judgement, we notify regardless of the user's threshold — the inbox should
not silently swallow these.

Messages are framed for public channels: each post names the suggested reviewers
(Slack @mention when email matches the workspace, otherwise their PostHog name).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Q

from slack_sdk.errors import SlackApiError

from posthog.models import User
from posthog.models.integration import Integration, SlackIntegration

from products.signals.backend.implementation_pr import fetch_implementation_pr_urls_for_reports
from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalSourceConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    enrich_reviewer_dicts_with_org_members,
    normalized_github_logins_from_suggested_reviewer_artefacts,
    resolve_org_github_login_to_users,
)

logger = logging.getLogger(__name__)

_SUMMARY_EXCERPT_MAX_LEN = 600
_SLACK_HEADER_MAX_LEN = 150

# Deep link opened by the PostHog Code desktop app. Override via env for dev (`posthog-code-dev`).
POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME = getattr(settings, "POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME", "posthog-code")

# Priority ranking — lower index is higher priority. Index used for threshold comparison.
_PRIORITY_ORDER: tuple[str, ...] = (
    AutonomyPriority.P0,
    AutonomyPriority.P1,
    AutonomyPriority.P2,
    AutonomyPriority.P3,
    AutonomyPriority.P4,
)

_SLACK_PRIORITY_LABELS: dict[str, str] = {
    AutonomyPriority.P0: "🆘 P0",
    AutonomyPriority.P1: "‼️ P1",
    AutonomyPriority.P2: "❗ P2",
    AutonomyPriority.P3: "⚠️ P3",
    AutonomyPriority.P4: "👀 P4",
}

_SOURCE_PRODUCT_LABELS: dict[str, str] = {
    choice.value: str(choice.label) for choice in SignalSourceConfig.SourceProduct
}


def _priority_rank(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return _PRIORITY_ORDER.index(value)
    except ValueError:
        return None


def _slack_priority_label(value: str) -> str:
    return _SLACK_PRIORITY_LABELS.get(value, value)


def _meets_min_priority(report_priority: str | None, min_priority: str | None) -> bool:
    """Whether a report with the given priority meets the user's min-priority threshold.

    `min_priority=None` notifies for every report. When the report has no priority
    (no priority_judgment artefact yet, or unrecognised value), we still notify —
    suppression would silently drop new inbox items, which the user did not opt into.
    """
    if min_priority is None:
        return True
    report_rank = _priority_rank(report_priority)
    if report_rank is None:
        return True
    min_rank = _priority_rank(min_priority)
    if min_rank is None:
        return True
    # Lower index = higher priority (P0 < P4).
    return report_rank <= min_rank


def _latest_priority(report: SignalReport) -> str | None:
    art = (
        report.artefacts.filter(type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT)
        .order_by("-created_at")
        .first()
    )
    if art is None:
        return None
    try:
        data = json.loads(art.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("priority")
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class _RecipientPresentation:
    # `<@U…>` mention if we resolved the user's Slack ID — only renders inside mrkdwn
    # blocks (header blocks are plain_text and would show the raw `<@U…>` string).
    slack_mention: str | None
    plain_name: str


def _resolve_suggested_reviewer_user_ids(report: SignalReport) -> set[int]:
    """Resolve the suggested-reviewer GitHub logins on the report to PostHog user IDs.

    Uses the same enrichment path the API uses so a user that connected their
    GitHub account after the report was generated is still picked up.
    """
    artefacts = list(
        report.artefacts.filter(
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        ).order_by("-created_at")
    )
    if not artefacts:
        return set()

    logins = normalized_github_logins_from_suggested_reviewer_artefacts(artefacts)
    if not logins:
        return set()
    login_map = resolve_org_github_login_to_users(report.team_id, logins)
    if not login_map:
        return set()

    # Enrich each artefact's payload to drop reviewers that didn't resolve to a user.
    resolved_user_ids: set[int] = set()
    for art in artefacts:
        try:
            parsed = json.loads(art.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed, list):
            continue
        enriched = enrich_reviewer_dicts_with_org_members(report.team_id, parsed, login_to_user=login_map)
        for entry in enriched:
            user = entry.get("user") if isinstance(entry, dict) else None
            if isinstance(user, dict) and user.get("id"):
                resolved_user_ids.add(int(user["id"]))
    return resolved_user_ids


def _notification_targets_for_report(report: SignalReport) -> list[SignalUserAutonomyConfig]:
    user_ids = _resolve_suggested_reviewer_user_ids(report)
    if not user_ids:
        return []

    return list(
        SignalUserAutonomyConfig.objects.filter(user_id__in=user_ids)
        .filter(slack_notification_integration__team_id=report.team_id)
        .exclude(Q(slack_notification_integration__isnull=True) | Q(slack_notification_channel__isnull=True))
        .exclude(slack_notification_channel="")
        .select_related("slack_notification_integration")
    )


def _channel_id_from_target(value: str) -> str:
    """Mirror `getSlackChannelIdFromTargetValue` in the frontend."""
    return value.split("|", 1)[0].strip()


def _channel_display_name(value: str) -> str:
    pipe = value.find("|")
    if pipe == -1:
        return value
    return value[pipe + 1 :].strip() or value[:pipe].strip()


def _posthog_user_display_name(user: User) -> str:
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(part for part in parts if part).strip()
    if name:
        return name
    email = (user.email or "").strip()
    if "@" in email:
        return email.split("@", 1)[0]
    return email or "Unknown user"


def lookup_slack_user_id_by_email(slack: SlackIntegration, email: str) -> str | None:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return None

    try:
        response = slack.client.users_lookupByEmail(email=normalized_email)
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        if error_code != "users_not_found":
            logger.warning(
                "signals_inbox_slack_user_email_lookup_failed",
                extra={"email": normalized_email, "error": error_code},
            )
        return None

    data = response.data if hasattr(response, "data") and isinstance(response.data, dict) else response
    if not isinstance(data, dict) or not data.get("ok"):
        return None

    slack_user = data.get("user")
    if not isinstance(slack_user, dict) or not slack_user.get("id"):
        return None
    return str(slack_user["id"])


def _recipient_presentation(
    user: User,
    slack: SlackIntegration,
    integration: Integration,
) -> _RecipientPresentation:
    plain_name = _posthog_user_display_name(user)
    slack_user_id = lookup_slack_user_id_by_email(slack, user.email) if user.email else None
    slack_mention = f"<@{slack_user_id}>" if slack_user_id else None
    return _RecipientPresentation(slack_mention=slack_mention, plain_name=plain_name)


def _recipient_label(recipient: _RecipientPresentation) -> str:
    # Mention pings the user inside mrkdwn; otherwise escape the plain name so it renders literally.
    return recipient.slack_mention or recipient.plain_name.replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;"
    )


def _format_source_product_labels(source_products: list[str]) -> str:
    if not source_products:
        return ""
    labels = [_SOURCE_PRODUCT_LABELS.get(product, product.replace("_", " ").title()) for product in source_products]
    return ", ".join(labels)


def _summary_excerpt(summary: str) -> str:
    """First line of the report description only, capped at 600 characters."""
    text = summary.strip()
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    if not first_line:
        return ""
    if len(first_line) <= _SUMMARY_EXCERPT_MAX_LEN:
        return first_line
    return first_line[: _SUMMARY_EXCERPT_MAX_LEN - 3].rstrip() + "..."


def _build_message_blocks(
    report: SignalReport,
    *,
    priority: str | None,
    source_products: list[str],
    recipients: list[_RecipientPresentation],
    implementation_pr_url: str | None = None,
) -> tuple[list[dict], str]:
    title_line = report.title or "New signals inbox item"
    header_text = f"📬 {title_line}"
    if len(header_text) > _SLACK_HEADER_MAX_LEN:
        header_text = header_text[: _SLACK_HEADER_MAX_LEN - 3] + "..."

    recipient_label = ", ".join(_recipient_label(recipient) for recipient in recipients)
    metadata_parts = [f"Matched to {recipient_label} per code"]
    if priority:
        metadata_parts.insert(0, _slack_priority_label(priority))

    body_parts: list[str] = [f"*{' • '.join(metadata_parts)}*"]
    summary_text = _summary_excerpt(report.summary or "")
    if summary_text:
        body_parts.append(summary_text)

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(body_parts)}},
    ]

    context_parts: list[str] = []
    if report.signal_count:
        signal_label = "signal" if report.signal_count == 1 else "signals"
        context_parts.append(f"{report.signal_count} {signal_label}")
    sources_line = _format_source_product_labels(source_products)
    if sources_line:
        context_parts.append(sources_line)
    context_parts.append("Inbox")
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "  ·  ".join(context_parts)}],
        }
    )

    action_elements: list[dict] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Open in PostHog Code", "emoji": True},
            "url": f"{POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME}://inbox/{report.id}",
        }
    ]
    if implementation_pr_url:
        action_elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Review PR in GitHub", "emoji": True},
                "url": implementation_pr_url,
            }
        )
    blocks.append({"type": "actions", "elements": action_elements})

    priority_suffix = f" ({priority})" if priority else ""
    recipient_names = ", ".join(recipient.plain_name for recipient in recipients)
    fallback_text = f"Inbox for {recipient_names}{priority_suffix}: {title_line}"
    return blocks, fallback_text


def dispatch_inbox_item_notifications(
    report_id: str,
    team_id: int,
    source_products: list[str] | None = None,
) -> int:
    """Send Slack notifications for a newly-ready report. Returns count of messages sent.

    Best-effort: per-target Slack errors are logged but do not raise. We only raise
    on programmer error (missing report). The caller is the temporal summary workflow,
    which already swallows notification exceptions.
    """
    try:
        report = SignalReport.objects.get(id=report_id, team_id=team_id)
    except SignalReport.DoesNotExist:
        logger.warning(
            "dispatch_inbox_item_notifications: report not found",
            extra={"report_id": report_id, "team_id": team_id},
        )
        return 0

    targets = _notification_targets_for_report(report)
    if not targets:
        return 0

    priority = _latest_priority(report)
    sources = source_products or []
    implementation_pr_url = fetch_implementation_pr_urls_for_reports([str(report.id)]).get(str(report.id))
    users_by_id = {user.id: user for user in User.objects.filter(id__in=[config.user_id for config in targets])}

    # Several reviewers can resolve to the same channel — group them so each channel gets a
    # single message that still tags every matched reviewer. Keyed by integration + channel id,
    # since the same channel id under a different integration is a distinct destination.
    channels: dict[tuple[int, str], list[SignalUserAutonomyConfig]] = {}
    for config in targets:
        if not _meets_min_priority(priority, config.slack_notification_min_priority):
            continue
        if config.user_id not in users_by_id:
            logger.warning(
                "signals_inbox_slack_notification_missing_user",
                extra={"report_id": report_id, "team_id": team_id, "user_id": config.user_id},
            )
            continue
        integration = config.slack_notification_integration
        channel = config.slack_notification_channel
        if integration is None or not channel:
            continue
        channels.setdefault((integration.id, _channel_id_from_target(channel)), []).append(config)

    sent = 0
    for configs in channels.values():
        # All configs in a group share the same integration and resolved channel id.
        integration = configs[0].slack_notification_integration
        channel = configs[0].slack_notification_channel
        if integration is None or not channel:
            continue

        try:
            slack = SlackIntegration(integration)
            recipients = [_recipient_presentation(users_by_id[config.user_id], slack, integration) for config in configs]
            blocks, text = _build_message_blocks(
                report,
                priority=priority,
                source_products=sources,
                recipients=recipients,
                implementation_pr_url=implementation_pr_url,
            )
            slack.client.chat_postMessage(
                channel=_channel_id_from_target(channel),
                blocks=blocks,
                text=text,
            )
            sent += 1
        except Exception:
            logger.exception(
                "Failed to deliver signals inbox-item Slack notification",
                extra={
                    "report_id": report_id,
                    "team_id": team_id,
                    "user_ids": [config.user_id for config in configs],
                    "channel": _channel_display_name(channel),
                },
            )
    return sent
