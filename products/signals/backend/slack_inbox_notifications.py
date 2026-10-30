"""Slack notifications for signals inbox items.

Mirrors the inbox Reports tab's actionability gate: a report notifies only if it's actionable
(its latest actionability judgment is immediately_actionable or requires_human_input) — READY is
enforced upstream. The team-default channel (if configured) receives every such report. Each
suggested reviewer is also routed to one destination: their own configured target if set (filtered
by their min-priority), otherwise the team-default channel. A personal target is either a channel
or the reviewer's own Slack account, which Slack delivers as a direct message. Reviewers sharing a
destination get a single post mentioning only the reviewers routed there.
All sends are best-effort.
"""

from __future__ import annotations

import re
import json
import logging
from collections.abc import Collection, Iterable

from django.conf import settings

from rest_framework import serializers
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.integrations import IntegrationManager, IntegrationRecord
from posthog.models import User
from posthog.models.integration import SlackIntegration
from posthog.ph_client import ph_scoped_capture
from posthog.slack.formatting import (
    channel_id_from_target as _channel_id_from_target,
    escape_slack_mrkdwn as _escape_mrkdwn,
    markdown_links_to_labels,
)
from posthog.slack.markdown import slack_markdown_block as _markdown_block

from products.signals.backend.assignment_flags import assignment_side_effects_allowed
from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalReportSlackThread,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.report_generation.resolve_reviewers import (
    enrich_reviewer_dicts_with_org_members,
    normalized_github_logins_from_suggested_reviewer_artefacts,
    normalized_user_uuids_from_suggested_reviewer_artefacts,
    resolve_org_github_login_to_users,
    resolve_org_users_by_uuid,
)
from products.signals.backend.report_urls import ReportLinkSource, build_report_url
from products.signals.backend.scout_authorship import report_is_hidden_from_inbox
from products.signals.backend.slack_formatting import (
    first_sentence as _first_sentence,
    prepare_slack_markdown as _prepare_markdown,
    strip_chart_references as _strip_chart_references,
)
from products.signals.backend.slack_notification_targets import is_slack_member_target, lookup_slack_user_id_by_email
from products.signals.backend.slack_report_threads import record_report_slack_thread
from products.slack_app.backend.facade.api import slack_followup_invite

# Actionability values shown in the inbox Reports tab. Slack notifications mirror that tab, so a
# report notifies iff its latest actionability judgment is one of these (and it's READY).
_ACTIONABLE_VALUES = frozenset(
    {ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value, ActionabilityChoice.REQUIRES_HUMAN_INPUT.value}
)

logger = logging.getLogger(__name__)

_SUMMARY_EXCERPT_MAX_LEN = 280
_SLACK_HEADER_MAX_LEN = 150
_INBOX_INVITE_UTM_TAGS = "utm_source=posthog&utm_campaign=signals_inbox&utm_medium=slack"
# Bound message size / avoid pinging a crowd.
_MAX_REVIEWER_MENTIONS = 5

# Deep link opened by the PostHog Desktop app. Override via env for dev (`posthog-code-dev`).
POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME = getattr(settings, "POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME", "posthog-code")

# Priority ranking — lower index is higher priority. Index used for threshold comparison.
_PRIORITY_ORDER: tuple[str, ...] = (
    AutonomyPriority.P0,
    AutonomyPriority.P1,
    AutonomyPriority.P2,
    AutonomyPriority.P3,
    AutonomyPriority.P4,
)

# Report titles are PR-style ("fix(scope): Description"). The inbox shows only the description, so
# Slack does too. Keep in sync with CONVENTIONAL_COMMIT_TITLE in frontend/inbox/utils/reportPresentation.ts.
_CONVENTIONAL_COMMIT_TITLE = re.compile(r"^(\w+)(?:\(([^)]*)\))?!?:\s*(.+)$")
# Matches only a heading named exactly "Impact", so "## Expected impact" stays out.
_IMPACT_SECTION = re.compile(r"(?ms)^## Impact[ \t]*\n(.*?)(?=^#{1,2} |\Z)")


def _priority_rank(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return _PRIORITY_ORDER.index(value)
    except ValueError:
        return None


def _meets_min_priority(report_priority: str | None, min_priority: str | None) -> bool:
    """Whether a report with the given priority meets the user's min-priority threshold.

    `min_priority=None` notifies for every report with a recognised priority.
    Missing or unrecognised report priorities do not notify because Slack
    notifications only go out once actionability and priority are persisted.
    """
    report_rank = _priority_rank(report_priority)
    if report_rank is None:
        return False
    if min_priority is None:
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


def _latest_actionability(report: SignalReport) -> str | None:
    art = (
        report.artefacts.filter(type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT)
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
    value = data.get("actionability")
    return value if isinstance(value, str) else None


def resolve_org_suggested_reviewer_user_ids(*, team_id: int, report_ids: Collection[str]) -> dict[str, set[int]]:
    """Resolve each report's latest reviewers within the team's organization.

    Callers must intersect these candidate IDs with project access before delivering content.
    """
    artefacts = list(
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report__team_id=team_id,
            report_id__in=report_ids,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        )
        .order_by("report_id", "-created_at")
        .distinct("report_id")
    )
    if not artefacts:
        return {}

    logins = normalized_github_logins_from_suggested_reviewer_artefacts(artefacts)
    user_uuids = normalized_user_uuids_from_suggested_reviewer_artefacts(artefacts)
    login_map = resolve_org_github_login_to_users(team_id, logins) if logins else {}
    uuid_map = resolve_org_users_by_uuid(team_id, user_uuids) if user_uuids else {}
    result: dict[str, set[int]] = {}
    for art in artefacts:
        report_logins = normalized_github_logins_from_suggested_reviewer_artefacts([art])
        unmapped_count = len(report_logins - login_map.keys())
        if unmapped_count:
            logger.info(
                "slack routing for report %s (team %d): %d of %d suggested reviewer login(s) map to no PostHog user",
                art.report_id,
                team_id,
                unmapped_count,
                len(report_logins),
            )
        try:
            parsed = json.loads(art.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed, list):
            continue
        enriched = enrich_reviewer_dicts_with_org_members(
            team_id, parsed, login_to_user=login_map, uuid_to_user=uuid_map, scout_display_names={}
        )
        user_ids: set[int] = set()
        for entry in enriched:
            user = entry.get("user") if isinstance(entry, dict) else None
            if isinstance(user, dict) and user.get("id"):
                user_ids.add(int(user["id"]))
        result[str(art.report_id)] = user_ids
    return result


def resolve_suggested_reviewer_user_ids(report: SignalReport) -> set[int]:
    """Resolve the report's suggested reviewers to users with project access.

    Uses the same enrichment path the API uses, so a reviewer stored by user uuid resolves whether
    or not they have GitHub linked, and one stored by login is still picked up after they connect
    their GitHub account.
    """
    user_ids = resolve_org_suggested_reviewer_user_ids(team_id=report.team_id, report_ids=[str(report.id)]).get(
        str(report.id), set()
    )
    if not user_ids:
        return set()
    return set(report.team.all_users_with_access().filter(id__in=user_ids).values_list("id", flat=True))


def _own_target_configs_by_user(team_id: int, user_ids: set[int]) -> dict[int, SignalUserAutonomyConfig]:
    """Per-user configs that name an own Slack target on this team's integration.

    The target is a channel or the reviewer's own Slack account. A reviewer absent from this map
    has no own target and falls back to the team default.
    """
    configs = (
        SignalUserAutonomyConfig.objects.filter(user_id__in=user_ids)
        .filter(slack_notification_integration__team_id=team_id)
        .exclude(slack_notification_channel__isnull=True)
        .exclude(slack_notification_channel="")
        .select_related("slack_notification_integration")
    )
    return {config.user_id: config for config in configs}


def _team_notification_target(team_id: int) -> tuple[IntegrationRecord, str] | None:
    """The team-default channel and the Slack workspace that owns it."""
    config = (
        SignalTeamConfig.objects.filter(team_id=team_id)
        .only("default_slack_notification_channel", "default_slack_notification_integration_id")
        .first()
    )
    channel = ((config.default_slack_notification_channel if config else None) or "").strip()
    if config is None or not channel:
        return None
    # Standard `slack` kind (not `slack-posthog-code`), matching the per-user path.
    slack_rows = IntegrationManager.slack.any
    bound_id = config.default_slack_notification_integration_id
    if bound_id is not None and (integration := slack_rows.get_many(team_id, [bound_id]).get(bound_id)):
        return integration, channel
    # A channel saved before the binding existed, or bound to a removed workspace, keeps the old
    # routing through the oldest workspace.
    legacy = slack_rows.find(team_id)
    return (legacy, channel) if legacy is not None else None


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


def _resolve_reviewer_mentions(slack: SlackIntegration, reviewer_users: list[User]) -> list[str]:
    # `<@U…>` mention when the reviewer's email resolves in this workspace, else escaped name.
    # A failed lookup (a missing users:read.email scope, a spent lookup budget) costs only the
    # mention. The next lookup fails the same way, so the remaining reviewers get names too.
    mentions: list[str] = []
    lookups_available = True
    for user in reviewer_users[:_MAX_REVIEWER_MENTIONS]:
        slack_user_id = None
        if user.email and lookups_available:
            try:
                slack_user_id = lookup_slack_user_id_by_email(slack, user.email)
            except (SlackApiError, serializers.ValidationError):
                lookups_available = False
        mentions.append(f"<@{slack_user_id}>" if slack_user_id else _escape_mrkdwn(_posthog_user_display_name(user)))
    return mentions


def _cap_excerpt(text: str) -> str:
    if len(text) <= _SUMMARY_EXCERPT_MAX_LEN:
        return text
    text = markdown_links_to_labels(text)
    if len(text) <= _SUMMARY_EXCERPT_MAX_LEN:
        return text
    return text[: _SUMMARY_EXCERPT_MAX_LEN - 3].rstrip() + "..."


def _summary_excerpt(summary: str) -> str:
    """First sentence of the report description's first line, capped at 280 characters."""
    text = summary.strip()
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    if not first_line:
        return ""
    return _cap_excerpt(_first_sentence(first_line))


def _impact_excerpt(summary: str) -> str:
    """First sentence of the summary's `## Impact` section, capped at 280 characters."""
    match = _IMPACT_SECTION.search(summary)
    if match is None:
        return ""
    section = match.group(1).strip()
    if not section:
        return ""
    first_paragraph = re.split(r"\n\s*\n", section, maxsplit=1)[0]
    return _cap_excerpt(_first_sentence(" ".join(line.strip() for line in first_paragraph.splitlines())))


def _display_title(title: str | None) -> str:
    title = (title or "").strip()
    if not title:
        return "New report"
    match = _CONVENTIONAL_COMMIT_TITLE.match(title)
    description = match.group(3).strip() if match else ""
    return description or title


def _build_message_blocks(report: SignalReport, *, reviewer_mentions: list[str]) -> tuple[list[dict], str]:
    title_line = _display_title(report.title)
    header_text = (
        title_line if len(title_line) <= _SLACK_HEADER_MAX_LEN else title_line[: _SLACK_HEADER_MAX_LEN - 3] + "..."
    )

    # The body is escaped once as a whole below, so the LLM-derived parts assembled here stay raw.
    # The `**` this adds is the one piece of Markdown the message means, and escaping leaves it be.
    body_parts: list[str] = []
    # Strip before excerpting so truncation can't slice a chart link mid-syntax.
    summary = _strip_chart_references(report.summary or "")
    summary_text = _summary_excerpt(summary)
    if summary_text:
        body_parts.append(summary_text)
    impact_text = _impact_excerpt(summary)
    if impact_text:
        body_parts.append(f"**Impact:** {impact_text}")
    if not body_parts:
        body_parts.append(f"**{title_line}**")

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        _markdown_block(_prepare_markdown("\n\n".join(body_parts))),
    ]

    # Mentions sit in mrkdwn, not plain_text, so the `<@U…>` token still pings the owner.
    if reviewer_mentions:
        owner_label = "Suggested owner" if len(reviewer_mentions) == 1 else "Suggested owners"
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"👤 {owner_label}: {' '.join(reviewer_mentions)}"}],
            }
        )

    action_elements: list[dict] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Review in PostHog", "emoji": True},
            "url": build_report_url(report.team_id, report.id, ReportLinkSource.SLACK),
        }
    ]
    blocks.append({"type": "actions", "elements": action_elements})

    return blocks, _escape_mrkdwn(title_line)


class _ChannelRoute:
    """One Slack destination and the reviewers routed to it (mentioned only there).

    The destination is a channel, or a member whose id Slack turns into a direct message.
    """

    def __init__(self, integration: IntegrationRecord, channel: str, *, is_team_channel: bool) -> None:
        self.integration = integration
        self.channel = channel
        self.is_team_channel = is_team_channel
        self.is_direct_message = is_slack_member_target(channel)
        self.users: list[User] = []


@frozen
class _Destination:
    integration: IntegrationRecord
    channel: str
    is_team_channel: bool


class _RouteTable:
    """The destinations one report is posted to, each collecting the reviewers it mentions.

    Keyed by (integration_id, channel_id) so a reviewer's own channel and the team default
    collapse into one post when they resolve to the same Slack channel.
    """

    def __init__(self) -> None:
        self._routes: dict[tuple[int, str], _ChannelRoute] = {}

    def add(self, destination: _Destination, *, user: User | None = None) -> None:
        key = (destination.integration.id, _channel_id_from_target(destination.channel))
        route = self._routes.get(key)
        if route is None:
            route = _ChannelRoute(
                destination.integration, destination.channel, is_team_channel=destination.is_team_channel
            )
            self._routes[key] = route
        elif destination.is_team_channel:
            route.is_team_channel = True
        if user is not None:
            route.users.append(user)

    def routes(self) -> list[_ChannelRoute]:
        return list(self._routes.values())


def _reviewer_destination(
    *,
    own_config: SignalUserAutonomyConfig | None,
    priority: str | None,
    team_integration: IntegrationRecord | None,
    team_channel: str | None,
) -> _Destination | None:
    """Where one suggested reviewer is notified: their own target if set, else the team default.

    `None` means this reviewer gets no notification at all.
    """
    if own_config is not None:
        if not _meets_min_priority(priority, own_config.slack_notification_min_priority):
            return None
        integration: IntegrationRecord | None = own_config.slack_notification_integration
        channel = own_config.slack_notification_channel
        is_team_channel = False
    elif team_integration is not None and team_channel:
        integration, channel, is_team_channel = team_integration, team_channel, True
    else:
        return None

    if integration is None or not channel:
        return None
    return _Destination(integration=integration, channel=channel, is_team_channel=is_team_channel)


def _build_reviewer_routes(
    report: SignalReport,
    *,
    priority: str | None,
    team_integration: IntegrationRecord | None,
    team_channel: str | None,
) -> list[_ChannelRoute]:
    """Route resolvable suggested reviewers to a destination, mentioning them there.

    Own target (filtered by the reviewer's min-priority) if set, else the team default. A reviewer
    filtered out of their own target is not mentioned in the team channel — that was their choice.
    Reviewers sharing a destination are grouped so each channel is posted to once, mentioning only
    its own reviewers. The team-default channel (if configured) receives every report, with no
    mentions when no reviewer is routed there.
    """
    reviewer_user_ids = resolve_suggested_reviewer_user_ids(report)
    reviewer_users = {user.id: user for user in User.objects.filter(id__in=reviewer_user_ids)}
    own_configs = _own_target_configs_by_user(report.team_id, reviewer_user_ids)

    table = _RouteTable()
    for user_id in sorted(reviewer_user_ids):
        user = reviewer_users.get(user_id)
        if user is None:
            continue
        destination = _reviewer_destination(
            own_config=own_configs.get(user_id),
            priority=priority,
            team_integration=team_integration,
            team_channel=team_channel,
        )
        if destination is None:
            continue
        table.add(destination, user=user)

    # The team channel gets every report. It mentions only the reviewers routed there, so a reviewer
    # with their own target is not pinged twice.
    if team_integration is not None and team_channel:
        table.add(_Destination(integration=team_integration, channel=team_channel, is_team_channel=True))

    return table.routes()


def _deliver_route_notification(
    report: SignalReport,
    route: _ChannelRoute,
    *,
    trigger: str,
) -> bool:
    """Post one report notification to a route's destination.

    Shared by the report-ready and reviewer-added dispatchers. Returns True if the top-level
    message was sent. Best-effort: Slack errors are logged, not raised.
    """
    channel_id = _channel_id_from_target(route.channel)
    log_context = {
        "report_id": str(report.id),
        "team_id": report.team_id,
        "channel": _channel_display_name(route.channel),
        "destination": "team" if route.is_team_channel else "user",
        "target_kind": "direct_message" if route.is_direct_message else "channel",
    }
    delivered = False
    try:
        slack = SlackIntegration(route.integration, source="signals_inbox")
        if route.is_direct_message and slack.get_user_by_id(channel_id) is None:
            # A member reachable when the target was saved can since have left or become a guest.
            logger.warning("Skipping signals inbox-item Slack DM to an ineligible member", extra=log_context)
            _capture_notification_delivered(report, route, trigger=trigger, delivered=False)
            return False
        # The only reviewer a direct message could mention is the person already reading it.
        mentions = [] if route.is_direct_message else _resolve_reviewer_mentions(slack, route.users)
        blocks, text = _build_message_blocks(report, reviewer_mentions=mentions)
        # Added here rather than inside the block builder, which stays free of the integration so it
        # can be tested without one. Approval is read now, not assumed from generation time: a
        # reviewer can be added to a retained report after the org revoked it.
        ai_enabled = bool(report.team.organization.is_ai_data_processing_approved)
        if invite := slack_followup_invite(route.integration, utm_tags=_INBOX_INVITE_UTM_TAGS, ai_enabled=ai_enabled):
            blocks.append(invite)
        if not assignment_side_effects_allowed(team_id=report.team_id, report_id=str(report.id)):
            return False
        response = slack.client.chat_postMessage(channel=channel_id, blocks=blocks, text=text)
        delivered = True
        thread_ts = response.get("ts") if hasattr(response, "get") else None
        # A member target opens a direct message, so the conversation Slack posted into is not the
        # id we sent. An inbound mention names the conversation, so that is what the link records.
        posted_channel = response.get("channel") if hasattr(response, "get") else None
        if thread_ts and (slack_workspace_id := route.integration.integration_id):
            record_report_slack_thread(
                slack_workspace_id=slack_workspace_id,
                team_id=report.team_id,
                report_id=str(report.id),
                integration_id=route.integration.id,
                channel=str(posted_channel or channel_id),
                thread_ts=str(thread_ts),
                kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
            )
    except Exception:
        logger.exception("Failed to deliver signals inbox-item Slack notification", extra=log_context)
    _capture_notification_delivered(report, route, trigger=trigger, delivered=delivered)
    return delivered


def _deliver_to_routes(
    report: SignalReport,
    routes: list[_ChannelRoute],
    *,
    trigger: str,
) -> int:
    """Post the report to every route, returning how many top-level messages were sent."""
    sent = 0
    for route in routes:
        if _deliver_route_notification(report, route, trigger=trigger):
            sent += 1
    return sent


def _capture_notification_delivered(
    report: SignalReport, route: _ChannelRoute, *, trigger: str, delivered: bool
) -> None:
    """Emit `signals_inbox_notification_delivered` for one destination's outcome.

    Nothing else measures this path, so a reviewer ping that is set up but never arrives looks the
    same as one nobody configured. The target itself names the customer's own channel or teammate,
    so only its kind travels.

    Best-effort: never raises, so analytics can't stop a notification.
    """
    try:
        team = report.team
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(team.uuid),
                event="signals_inbox_notification_delivered",
                properties={
                    "team_id": report.team_id,
                    "report_id": str(report.id),
                    "trigger": trigger,
                    "destination": "team" if route.is_team_channel else "user",
                    "target_kind": "direct_message" if route.is_direct_message else "channel",
                    "reviewer_count": len(route.users),
                    "delivered": delivered,
                },
                groups=groups(team.organization, team),
            )
    except Exception:
        logger.exception("Failed to capture signals_inbox_notification_delivered for report %s", report.id)


def dispatch_inbox_item_notifications(report_id: str, team_id: int) -> int:
    """Send Slack notifications for a newly-ready report.

    Returns the number of notification messages sent (one per destination channel). Evidence is
    not posted to Slack: the report shows it in a normalized form, so the message links there.

    Best-effort: per-destination Slack errors are logged, not raised.
    """
    if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
        return 0

    try:
        report = SignalReport.objects.get(id=report_id, team_id=team_id)
    except SignalReport.DoesNotExist:
        logger.warning(
            "dispatch_inbox_item_notifications: report not found",
            extra={"report_id": report_id, "team_id": team_id},
        )
        return 0

    if report_is_hidden_from_inbox(team_id, report_id):
        logger.info(
            "dispatch_inbox_item_notifications: authoring scout keeps reports out of the inbox, skipping",
            extra={"report_id": report_id, "team_id": team_id},
        )
        return 0

    # Mirror the inbox Reports tab: notify only for actionable reports (READY is enforced upstream
    # in the notification activity). Priority is read below for min-priority routing, but
    # it's optional now — an actionable report notifies even without a priority.
    if _latest_actionability(report) not in _ACTIONABLE_VALUES:
        logger.info(
            "dispatch_inbox_item_notifications: report not actionable, skipping",
            extra={"report_id": report_id, "team_id": team_id},
        )
        return 0

    priority = _latest_priority(report)
    team_target = _team_notification_target(team_id)
    team_integration, team_channel = team_target if team_target is not None else (None, None)

    routes = _build_reviewer_routes(
        report,
        priority=priority,
        team_integration=team_integration,
        team_channel=team_channel,
    )
    if not routes:
        # No channel to deliver to: no reviewer resolved to a destination and no notification channel
        # is configured for the team (no per-user own channel and no team default). Log the inputs so
        # it's diagnosable.
        logger.info(
            "dispatch_inbox_item_notifications: no notification channel configured, skipping",
            extra={
                "report_id": report_id,
                "team_id": team_id,
                "priority": priority,
                "has_team_integration": team_integration is not None,
                "has_team_channel": team_channel is not None,
            },
        )
        return 0

    sent = _deliver_to_routes(report, routes, trigger="report_ready")
    logger.info(
        "dispatch_inbox_item_notifications: complete",
        extra={"report_id": report_id, "team_id": team_id, "messages_sent": sent, "routes": len(routes)},
    )
    return sent


def _stripped_nonempty(values: Iterable[str] | None) -> set[str]:
    return {value.strip() for value in values or () if value and value.strip()}


def _resolve_added_reviewer_user_ids(
    report: SignalReport, *, logins: set[str], user_uuids: set[str], exclude_user_id: int | None
) -> set[int]:
    """PostHog user IDs for the reviewers just added, restricted to the project's access set.

    A reviewer added by uuid may have no GitHub login at all, so both identities are resolved: the
    personal ping is the whole point of this path, and losing it would leave them unnotified.
    """
    resolved_users = [
        *(resolve_org_github_login_to_users(report.team_id, logins).values() if logins else []),
        *(resolve_org_users_by_uuid(report.team_id, user_uuids).values() if user_uuids else []),
    ]
    user_ids = {user.id for user in resolved_users if user.id != exclude_user_id}
    if not user_ids:
        return set()
    # Org membership alone isn't enough: on a private project an org member without project
    # access must not receive the report's contents, so intersect with the project's access set.
    return user_ids & set(report.team.all_users_with_access().filter(id__in=user_ids).values_list("id", flat=True))


def _build_added_reviewer_routes(team_id: int, user_ids: set[int], priority: str | None) -> list[_ChannelRoute]:
    """Route each added reviewer to their own configured target, with no team-default fallback."""
    own_configs = _own_target_configs_by_user(team_id, user_ids)
    users_by_id = {user.id: user for user in User.objects.filter(id__in=user_ids)}

    table = _RouteTable()
    for user_id in sorted(user_ids):
        user = users_by_id.get(user_id)
        config = own_configs.get(user_id)
        if user is None or config is None:
            continue
        # An unprioritized report still pings a reviewer with no min-priority threshold: the
        # initial path would have delivered it via the team channel, but this path has no
        # fallback, so `_meets_min_priority`'s no-priority-never-notifies rule would lose it.
        min_priority = config.slack_notification_min_priority
        if (priority is not None or min_priority is not None) and not _meets_min_priority(priority, min_priority):
            continue
        integration = config.slack_notification_integration
        channel = config.slack_notification_channel
        if integration is None or not channel:
            continue
        table.add(_Destination(integration=integration, channel=channel, is_team_channel=False), user=user)
    return table.routes()


def dispatch_reviewer_added_notifications(
    report_id: str,
    team_id: int,
    added_github_logins: Iterable[str],
    exclude_user_id: int | None = None,
    added_user_uuids: Iterable[str] | None = None,
) -> int:
    """Notify reviewers a human just added to an already-actionable report.

    Unlike `dispatch_inbox_item_notifications` — fired once, from the report-generation
    pipeline, when a report first becomes READY — this fires when someone manually adds
    reviewers afterwards, so a reviewer who wasn't on the report at generation time still
    hears about it. It targets only the given logins and only their own configured Slack
    target: a manual add is a personal ping, so there's no team-default fallback (that
    would ping the whole team for a one-person add) and a reviewer with no personal target
    set up (or whose min-priority filters the report out) gets nothing.

    Gated on the same READY + actionable condition as the initial notification, so it only
    fires for reports that would themselves have notified. `exclude_user_id` drops the actor
    so someone adding themselves isn't pinged. Best-effort; returns messages sent.
    """
    if not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
        return 0

    added_logins = {login.lower() for login in _stripped_nonempty(added_github_logins)}
    added_uuids = _stripped_nonempty(added_user_uuids)
    if not added_logins and not added_uuids:
        return 0

    try:
        report = SignalReport.objects.get(id=report_id, team_id=team_id)
    except SignalReport.DoesNotExist:
        logger.warning(
            "dispatch_reviewer_added_notifications: report not found",
            extra={"report_id": report_id, "team_id": team_id},
        )
        return 0

    # Mirror the initial notification's gate: only reports actually surfaced in the inbox
    # (READY and actionable) notify. Status is checked here because — unlike the generation
    # pipeline — this path has no upstream READY guarantee.
    if report.status != SignalReport.Status.READY or _latest_actionability(report) not in _ACTIONABLE_VALUES:
        return 0

    user_ids = _resolve_added_reviewer_user_ids(
        report, logins=added_logins, user_uuids=added_uuids, exclude_user_id=exclude_user_id
    )
    if not user_ids:
        return 0

    priority = _latest_priority(report)
    routes = _build_added_reviewer_routes(team_id, user_ids, priority)
    if not routes:
        return 0

    sent = _deliver_to_routes(report, routes, trigger="reviewer_added")
    logger.info(
        "dispatch_reviewer_added_notifications: complete",
        extra={"report_id": report_id, "team_id": team_id, "messages_sent": sent, "routes": len(routes)},
    )
    return sent
