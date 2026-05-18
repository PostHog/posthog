"""Slack notifications for signals inbox items.

When a report transitions to READY (a new inbox item lands), we look up the
suggested reviewers from its `suggested_reviewers` artefact, resolve them to
PostHog users, and dispatch a Slack message to each user that has configured a
Slack channel and integration in their `SignalUserAutonomyConfig`.

Each user's `slack_notification_min_priority` filters out reports below the
configured threshold (P0 is highest). When the report has no priority
judgement, we notify regardless of the user's threshold — the inbox should
not silently swallow these.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from django.db.models import Q

from posthog.models.integration import Integration, SlackIntegration

from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    enrich_reviewer_dicts_with_org_members,
    normalized_github_logins_from_suggested_reviewer_artefacts,
    resolve_org_github_login_to_users,
)

logger = logging.getLogger(__name__)


# Priority ranking — lower index is higher priority. Index used for threshold comparison.
_PRIORITY_ORDER: tuple[str, ...] = (
    AutonomyPriority.P0,
    AutonomyPriority.P1,
    AutonomyPriority.P2,
    AutonomyPriority.P3,
    AutonomyPriority.P4,
)


def _priority_rank(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return _PRIORITY_ORDER.index(value)
    except ValueError:
        return None


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


def _suggested_reviewer_artefacts(report: SignalReport) -> list[SignalReportArtefact]:
    return list(
        report.artefacts.filter(
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        ).order_by("-created_at")
    )


@dataclass(frozen=True)
class _NotificationTarget:
    user_id: int
    config: SignalUserAutonomyConfig


def _resolve_suggested_reviewer_user_ids(report: SignalReport) -> set[int]:
    """Resolve the suggested-reviewer GitHub logins on the report to PostHog user IDs.

    Uses the same enrichment path the API uses so a user that connected their
    GitHub account after the report was generated is still picked up.
    """
    artefacts = _suggested_reviewer_artefacts(report)
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


def _notification_targets_for_report(report: SignalReport) -> list[_NotificationTarget]:
    user_ids = _resolve_suggested_reviewer_user_ids(report)
    if not user_ids:
        return []

    configs = (
        SignalUserAutonomyConfig.objects.filter(user_id__in=user_ids)
        .exclude(Q(slack_notification_integration__isnull=True) | Q(slack_notification_channel__isnull=True))
        .exclude(slack_notification_channel="")
        .select_related("slack_notification_integration")
    )
    return [_NotificationTarget(user_id=cfg.user_id, config=cfg) for cfg in configs]


def _channel_id_from_target(value: str) -> str:
    """Mirror `getSlackChannelIdFromTargetValue` in the frontend."""
    return value.split("|", 1)[0].strip()


def _channel_display_name(value: str) -> str:
    pipe = value.find("|")
    if pipe == -1:
        return value
    return value[pipe + 1 :].strip() or value[:pipe].strip()


def _build_message_blocks(
    report: SignalReport,
    priority: str | None,
    source_products: list[str],
) -> tuple[list[dict], str]:
    title_line = report.title or "New signals inbox item"
    priority_chip = f" · {priority}" if priority else ""
    sources_line = ", ".join(source_products) if source_products else ""

    header_text = f"New inbox item — needs your review{priority_chip}"
    if len(header_text) > 150:
        header_text = header_text[:147] + "..."

    summary_text = report.summary or ""
    if len(summary_text) > 2500:
        summary_text = summary_text[:2497] + "..."

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title_line}*"}},
    ]
    if summary_text:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary_text}})

    context_parts: list[str] = []
    if priority:
        context_parts.append(f"Priority: *{priority}*")
    if sources_line:
        context_parts.append(f"Sources: {sources_line}")
    context_parts.append("You're a suggested reviewer on this report.")
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "  ·  ".join(context_parts)}],
        }
    )
    return blocks, header_text


def _send_one(
    integration: Integration,
    channel_value: str,
    blocks: list[dict],
    text: str,
) -> None:
    slack = SlackIntegration(integration)
    slack.client.chat_postMessage(
        channel=_channel_id_from_target(channel_value),
        blocks=blocks,
        text=text,
    )


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
    blocks, text = _build_message_blocks(report, priority, sources)

    sent = 0
    for target in targets:
        config = target.config
        if not _meets_min_priority(priority, config.slack_notification_min_priority):
            continue
        integration = config.slack_notification_integration
        channel = config.slack_notification_channel
        if integration is None or not channel:
            continue
        try:
            _send_one(integration, channel, blocks, text)
            sent += 1
        except Exception:
            logger.exception(
                "Failed to deliver signals inbox-item Slack notification",
                extra={
                    "report_id": report_id,
                    "team_id": team_id,
                    "user_id": target.user_id,
                    "channel": _channel_display_name(channel),
                },
            )
    return sent
