"""Slack notifications for signals inbox items.

Mirrors the inbox Reports tab's actionability gate: a report notifies only if it's actionable
(its latest actionability judgment is immediately_actionable or requires_human_input) — READY is
enforced upstream. The team-default channel (if configured) receives every such report. Each
suggested reviewer is also routed to one destination: their own configured target if set (filtered
by their min-priority), otherwise the team-default channel. A personal target is either a channel
or the reviewer's own Slack account, which Slack delivers as a direct message. Reviewers sharing a
destination get a single post mentioning only the reviewers routed there.
Already-addressed reports still reach the team channel, but do not notify suggested reviewers.
All sends are best-effort.
"""

from __future__ import annotations

import re
import json
import logging
from collections.abc import Collection, Iterable

from django.conf import settings

from markdown_to_mrkdwn import SlackMarkdownConverter
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
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalReportSlackThread,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_content_gates import organization_inbox_slack_section_blocks_enabled
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
    is_safe_slack_http_url,
    prepare_slack_markdown as _prepare_markdown,
    slack_text_length,
    strip_chart_references as _strip_chart_references,
    truncate_slack_text,
)
from products.signals.backend.slack_notification_targets import is_slack_member_target, lookup_slack_user_id_by_email
from products.signals.backend.slack_report_threads import record_report_slack_thread
from products.signals.backend.task_run_artefacts import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.typed_report_links import incoming_links
from products.slack_app.backend.facade.api import slack_followup_invite, slack_report_implementation_button
from products.tasks.backend.facade import api as tasks_facade

# Actionability values shown in the inbox Reports tab. Slack notifications mirror that tab, so a
# report notifies iff its latest actionability judgment is one of these (and it's READY).
_ACTIONABLE_VALUES = frozenset(
    {ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value, ActionabilityChoice.REQUIRES_HUMAN_INPUT.value}
)

logger = logging.getLogger(__name__)

_SUMMARY_EXCERPT_MAX_LEN = 280
_SLACK_HEADER_MAX_LEN = 150
_SLACK_CONTEXT_MAX_LEN = 3000
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
# Keep in sync with PRIORITY_TAG_TYPE in frontend/inbox/filterOptions.tsx, so Slack and the inbox agree.
_PRIORITY_EMOJI: dict[str, str] = {
    AutonomyPriority.P0: "🔴",
    AutonomyPriority.P1: "🟠",
    AutonomyPriority.P2: "🟡",
    AutonomyPriority.P3: "🔵",
    AutonomyPriority.P4: "⚪️",
}

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


def _latest_actionability_judgment(report: SignalReport) -> dict:
    art = (
        report.artefacts.filter(type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT)
        .order_by("-created_at")
        .first()
    )
    if art is None:
        return {}
    try:
        data = json.loads(art.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _offers_implementation(judgment: dict) -> bool:
    """Whether the message offers Implement: the research says the fix is ready and nobody has started it."""
    return (
        judgment.get("actionability") == ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value
        and judgment.get("already_addressed") is not True
    )


def _implementation_underway(report: SignalReport) -> bool:
    """Whether the report has a pull request or an implementation run that has not ended.

    The inbox then shows View task instead of the Implement choices, so the message must not offer
    Implement. Auto-start often opens the pull request before the notification goes out.
    """
    report_id = str(report.id)
    if fetch_implementation_prs_for_reports([report_id], team_id=report.team_id, using="default").get(report_id):
        return True
    task_ids = [
        run.task_id
        for run in SignalReport.associated_task_runs(
            report_id=report_id, team_id=report.team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
        )
    ]
    return any(not run.is_terminal for run in tasks_facade.get_latest_run_by_task(task_ids).values())


def _should_offer_implementation(report: SignalReport, judgment: dict) -> bool:
    """Whether the message offers Implement, matching when the inbox offers its Implement choices."""
    if not _offers_implementation(judgment):
        return False
    # A plan parent has no run of its own: the reports that are part of it do the work.
    if incoming_links(team_id=report.team_id, report_id=report.id, kinds=(ReportLinkKind.PART_OF,)):
        return False
    return not _implementation_underway(report)


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


@frozen
class _OwnTarget:
    integration: IntegrationRecord
    channel: str
    min_priority: str | None


def _own_target_configs_by_user(team_id: int, user_ids: set[int]) -> dict[int, _OwnTarget]:
    """Per-user configs that name an own Slack target on this team's integration.

    The target is a channel or the reviewer's own Slack account. A reviewer absent from this map
    has no own target and falls back to the team default.
    """
    configs = list(
        SignalUserAutonomyConfig.objects.filter(user_id__in=user_ids, slack_notification_integration_id__isnull=False)
        .exclude(slack_notification_channel__isnull=True)
        .exclude(slack_notification_channel="")
    )
    integrations = IntegrationManager.slack.any.get_many(
        team_id,
        {config.slack_notification_integration_id for config in configs if config.slack_notification_integration_id},
    )
    return {
        config.user_id: _OwnTarget(
            integration=integrations[config.slack_notification_integration_id],
            channel=config.slack_notification_channel or "",
            min_priority=config.slack_notification_min_priority,
        )
        for config in configs
        if config.slack_notification_integration_id in integrations
    }


def _team_notification_target(team_id: int, *, priority: str | None) -> tuple[IntegrationRecord, str] | None:
    """The team-default channel and the Slack workspace that owns it."""
    config = (
        SignalTeamConfig.objects.filter(team_id=team_id)
        .only(
            "default_slack_notification_channel",
            "default_slack_notification_integration_id",
            "default_slack_notification_min_priority",
        )
        .first()
    )
    channel = ((config.default_slack_notification_channel if config else None) or "").strip()
    if config is None or not channel:
        return None
    if config.default_slack_notification_min_priority and not _meets_min_priority(
        priority, config.default_slack_notification_min_priority
    ):
        return None
    integration = _team_notification_integration(team_id, config)
    return (integration, channel) if integration is not None else None


def _team_notification_integration(team_id: int, config: SignalTeamConfig) -> IntegrationRecord | None:
    # Standard `slack` kind (not `slack-posthog-code`), matching the per-user path.
    slack_rows = IntegrationManager.slack.any
    bound_id = config.default_slack_notification_integration_id
    if bound_id is not None and (integration := slack_rows.get_many(team_id, [bound_id]).get(bound_id)):
        return integration
    # A channel saved before the binding existed, or bound to a removed workspace, keeps the old
    # routing through the oldest workspace.
    return slack_rows.find(team_id)


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


def _section_body(markdown: str) -> str:
    def safe_token(match: re.Match[str]) -> str:
        destination = match.group(0)[1:-1].partition("|")[0]
        return match.group(0) if is_safe_slack_http_url(destination) else _escape_mrkdwn(match.group(0))

    # Conversion creates Slack tokens, so only HTTP links may survive in the untrusted body.
    converted = SlackMarkdownConverter().convert(markdown)
    return truncate_slack_text(re.sub(r"<[^<>]*>|[<>]", safe_token, converted), 3000)


def _owner_context_text(reviewer_labels: list[str], *, max_length: int = _SLACK_CONTEXT_MAX_LEN) -> str:
    owner_label = "Suggested owner" if len(reviewer_labels) == 1 else "Suggested owners"
    prefix = f"👤 {owner_label}:"
    text = f"{prefix} {' '.join(reviewer_labels)}"
    if slack_text_length(text) <= max_length:
        return text

    text = prefix
    for index, label in enumerate(reviewer_labels):
        remaining = len(reviewer_labels) - index - 1
        suffix = f" (+{remaining} more)" if remaining else ""
        if slack_text_length(text) + 1 + slack_text_length(label) + len(suffix) > max_length:
            return f"{text} (+{remaining + 1} more)"
        text += f" {label}"
    return text


def _build_message_blocks(
    report: SignalReport,
    *,
    reviewer_labels: list[str],
    use_section_blocks: bool = False,
    priority: str | None = None,
    offer_implementation: bool = False,
    slack_integration_id: int | None = None,
) -> tuple[list[dict], str]:
    title_line = _display_title(report.title)
    header_text = (
        title_line if len(title_line) <= _SLACK_HEADER_MAX_LEN else title_line[: _SLACK_HEADER_MAX_LEN - 3] + "..."
    )

    # The body is prepared as a whole below, so the LLM-derived parts assembled here stay raw.
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

    body = _prepare_markdown("\n\n".join(body_parts))
    body_block = (
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _section_body(body), "verbatim": True},
        }
        if use_section_blocks
        else _markdown_block(body)
    )
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        body_block,
    ]

    context_parts: list[str] = []
    if priority_emoji := _PRIORITY_EMOJI.get(priority or ""):
        context_parts.append(f"{priority_emoji} *{priority}*")
    # Plain-text blocks would show the raw mention token instead of resolving the user.
    if reviewer_labels:
        prefix_length = slack_text_length(" · ".join(context_parts) + " · ") if context_parts else 0
        context_parts.append(_owner_context_text(reviewer_labels, max_length=_SLACK_CONTEXT_MAX_LEN - prefix_length))
    if context_parts:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(context_parts), "verbatim": True}]}
        )

    action_elements: list[dict] = []
    if offer_implementation and slack_integration_id is not None:
        action_elements.append(slack_report_implementation_button(slack_integration_id))
    action_elements.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Review in PostHog", "emoji": True},
            "url": build_report_url(report.team_id, report.id, ReportLinkSource.SLACK),
        }
    )
    blocks.append({"type": "actions", "elements": action_elements})

    return blocks, _escape_mrkdwn(title_line)


class _ChannelRoute:
    """One Slack destination and the reviewers notified or shown there.

    The destination is a channel, or a member whose id Slack turns into a direct message.
    """

    def __init__(self, integration: IntegrationRecord, channel: str, *, is_team_channel: bool) -> None:
        self.integration = integration
        self.channel = channel
        self.is_team_channel = is_team_channel
        self.is_direct_message = is_slack_member_target(channel)
        self.users: list[User] = []
        self.owner_users: dict[int, User] = {}


@frozen
class _Destination:
    integration: IntegrationRecord
    channel: str
    is_team_channel: bool


class _RouteTable:
    """The destinations one report is posted to, with reviewers to notify and display.

    Keyed by (integration_id, channel_id) so a reviewer's own channel and the team default
    collapse into one post when they resolve to the same Slack channel.
    """

    def __init__(self) -> None:
        self._routes: dict[tuple[int, str], _ChannelRoute] = {}

    def add(self, destination: _Destination, *, user: User | None = None, owner_users: Iterable[User] = ()) -> None:
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
            route.owner_users[user.id] = user
        for owner_user in owner_users:
            route.owner_users[owner_user.id] = owner_user

    def routes(self) -> list[_ChannelRoute]:
        return list(self._routes.values())


def _reviewer_destination(
    *,
    own_config: _OwnTarget | None,
    priority: str | None,
    team_integration: IntegrationRecord | None,
    team_channel: str | None,
) -> _Destination | None:
    """Where one suggested reviewer is notified: their own target if set, else the team default.

    `None` means this reviewer gets no notification at all.
    """
    if own_config is not None:
        if not _meets_min_priority(priority, own_config.min_priority):
            return None
        integration: IntegrationRecord | None = own_config.integration
        channel = own_config.channel
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
    """Route resolvable suggested reviewers to a destination.

    Own target (filtered by the reviewer's min-priority) if set, else the team default. A reviewer
    filtered out of their own target is not pinged. Reviewers sharing a destination are grouped so
    each channel is posted to once. The team-default channel receives every report and shows every
    suggested owner. It pings only the reviewers routed there.
    """
    reviewer_user_ids = (
        set() if report.latest_already_addressed is True else resolve_suggested_reviewer_user_ids(report)
    )
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

    if team_integration is not None and team_channel:
        table.add(
            _Destination(integration=team_integration, channel=team_channel, is_team_channel=True),
            owner_users=(reviewer_users[user_id] for user_id in sorted(reviewer_users)),
        )

    return table.routes()


def _deliver_route_notification(
    report: SignalReport,
    route: _ChannelRoute,
    *,
    trigger: str,
    priority: str | None,
    offer_implementation: bool,
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
        if route.is_direct_message:
            reviewer_labels: list[str] = []
        else:
            reviewer_labels = _resolve_reviewer_mentions(slack, route.users)
            mentioned_user_ids = {user.id for user in route.users}
            reviewer_labels.extend(
                _escape_mrkdwn(_posthog_user_display_name(user))
                for user_id, user in route.owner_users.items()
                if user_id not in mentioned_user_ids
            )
        blocks, text = _build_message_blocks(
            report,
            reviewer_labels=reviewer_labels,
            use_section_blocks=organization_inbox_slack_section_blocks_enabled(report.team.organization_id),
            priority=priority,
            offer_implementation=offer_implementation,
            slack_integration_id=route.integration.id,
        )
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
    priority: str | None,
    offer_implementation: bool,
) -> int:
    """Post the report to every route, returning how many top-level messages were sent."""
    sent = 0
    for route in routes:
        if _deliver_route_notification(
            report, route, trigger=trigger, priority=priority, offer_implementation=offer_implementation
        ):
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
    actionability = _latest_actionability_judgment(report)
    if actionability.get("actionability") not in _ACTIONABLE_VALUES:
        logger.info(
            "dispatch_inbox_item_notifications: report not actionable, skipping",
            extra={"report_id": report_id, "team_id": team_id},
        )
        return 0

    priority = _latest_priority(report)
    team_target = _team_notification_target(team_id, priority=priority)
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

    sent = _deliver_to_routes(
        report,
        routes,
        trigger="report_ready",
        priority=priority,
        offer_implementation=_should_offer_implementation(report, actionability),
    )
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
        min_priority = config.min_priority
        if (priority is not None or min_priority is not None) and not _meets_min_priority(priority, min_priority):
            continue
        table.add(
            _Destination(integration=config.integration, channel=config.channel, is_team_channel=False), user=user
        )
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
    actionability = _latest_actionability_judgment(report)
    if report.status != SignalReport.Status.READY or actionability.get("actionability") not in _ACTIONABLE_VALUES:
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

    sent = _deliver_to_routes(
        report,
        routes,
        trigger="reviewer_added",
        priority=priority,
        offer_implementation=_should_offer_implementation(report, actionability),
    )
    logger.info(
        "dispatch_reviewer_added_notifications: complete",
        extra={"report_id": report_id, "team_id": team_id, "messages_sent": sent, "routes": len(routes)},
    )
    return sent


def _note_mention_destination(
    user: User, own_config: _OwnTarget | None, team_integration: IntegrationRecord | None
) -> _Destination | None:
    """Where one mentioned person hears about a note mention.

    Their own Slack target answers first, with no min-priority filter, because a mention is a direct
    ping and not a report digest. Without one, a direct message through the team's inbox workspace
    reaches them when their PostHog email matches a workspace member. The team channel is never
    used, so one mention does not ping the whole team.
    """
    if own_config is not None and own_config.channel:
        return _Destination(integration=own_config.integration, channel=own_config.channel, is_team_channel=False)
    if team_integration is None:
        return None
    member_id = lookup_slack_user_id_by_email(SlackIntegration(team_integration, source="signals_inbox"), user.email)
    if member_id is None:
        return None
    return _Destination(integration=team_integration, channel=member_id, is_team_channel=False)


def _note_mention_blocks(
    report: SignalReport, *, author_name: str, recipient_label: str, text: str
) -> tuple[list[dict], str]:
    url = build_report_url(report.team_id, report.id, ReportLinkSource.SLACK)
    title = _escape_mrkdwn(_display_title(report.title))
    headline = f"*{_escape_mrkdwn(author_name)}* mentioned {recipient_label} on <{url}|{title}>"
    quoted = "\n".join(f">{line}" for line in _escape_mrkdwn(text).splitlines() or [""])
    body = truncate_slack_text(f"{headline}\n{quoted}", 2900)
    # Slack shows the fallback in notification previews, so it is escaped like the body.
    fallback = _escape_mrkdwn(
        f"{author_name} mentioned {recipient_label} on a report: {report.title or 'Untitled report'}"
    )
    # `verbatim` keeps `@here` and `@channel` in the note as text, so a mention never pings a whole channel.
    return [{"type": "section", "text": {"type": "mrkdwn", "text": body, "verbatim": True}}], fallback


@frozen
class NoteMentionSlackResult:
    sent: int
    # People whose Slack lookup ran out of the workspace's lookup budget, to try again after it refills.
    deferred_user_ids: tuple[int, ...]


def deliver_report_note_mention_to_slack(
    report: SignalReport, users: Collection[User], *, author_name: str, text: str
) -> NoteMentionSlackResult:
    """Tell each mentioned person about a note mention in Slack, where Slack is set up for them.

    The caller has already checked each person's Inbox and project access. Best effort per person.
    """
    if not users:
        return NoteMentionSlackResult(sent=0, deferred_user_ids=())
    config = (
        SignalTeamConfig.objects.filter(team_id=report.team_id)
        .only("default_slack_notification_channel", "default_slack_notification_integration_id")
        .first()
    )
    inbox_slack_set_up = config is not None and (
        config.default_slack_notification_integration_id is not None
        or bool((config.default_slack_notification_channel or "").strip())
    )
    team_integration = _team_notification_integration(report.team_id, config) if config and inbox_slack_set_up else None
    own_configs = _own_target_configs_by_user(report.team_id, {user.id for user in users})

    sent = 0
    deferred: list[int] = []
    for user in users:
        log_context = {"report_id": str(report.id), "team_id": report.team_id}
        try:
            destination = _note_mention_destination(user, own_configs.get(user.id), team_integration)
            if destination is None:
                continue
            slack = SlackIntegration(destination.integration, source="signals_inbox")
            channel_id = _channel_id_from_target(destination.channel)
            is_direct_message = is_slack_member_target(destination.channel)
            # The same fail-closed check as report DMs: a member can have become a guest or left since.
            if is_direct_message and slack.get_user_by_id(channel_id) is None:
                logger.warning("Skipping a report note mention DM to an ineligible member", extra=log_context)
                continue
            recipient_label = "you" if is_direct_message else _escape_mrkdwn(_posthog_user_display_name(user))
            blocks, fallback = _note_mention_blocks(
                report, author_name=author_name, recipient_label=recipient_label, text=text
            )
            slack.client.chat_postMessage(channel=channel_id, blocks=blocks, text=fallback)
            sent += 1
        except serializers.ValidationError:
            # The member lookup budget is shared by the workspace and refills each minute.
            deferred.append(user.id)
        except Exception:
            logger.warning("Failed to send a report note mention to Slack", extra=log_context, exc_info=True)
    return NoteMentionSlackResult(sent=sent, deferred_user_ids=tuple(deferred))
