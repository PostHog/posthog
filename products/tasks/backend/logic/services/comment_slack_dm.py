"""Slack DM delivery for PostHog Code comment notifications.

A second channel for the three recipient kinds the in-app Activity feed already gets: a mention,
a reply to your comment, a comment on something you own. Recipients and the personal-channel
exclusion are decided by ``comment_activity``; this module only decides whether each recipient
wants a DM, may still see the comment, and where to send it.

Delivery is best-effort. The Activity row is the durable notification, so a Slack failure is
logged and dropped rather than retried — which also means a retry can't double-DM someone without
a per-recipient sent marker to store.
"""

from collections.abc import Callable, Mapping
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings

import structlog

from posthog.comment.access import task_comment_target_is_accessible
from posthog.comment.formatting import escape_slack_mrkdwn, rich_content_to_slack_payload
from posthog.helpers.slack_identity import resolve_slack_user
from posthog.models.comment import Comment
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import NOTIFICATION_DEFAULTS, User
from posthog.models.user_integration import UserIntegration
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.slack_app.backend.services.slack_user_info import lookup_slack_user_id_by_email
from products.tasks.backend.models import Task, TaskCommentActivity

logger = structlog.get_logger(__name__)

SLACK_DM_SETTING = "task_comments_slack_dm"

# Slack allows 3000 characters per section; a DM that long is unreadable, and the link to the full
# thread is right there in the heading.
_BODY_LIMIT = 800
_MAX_MENTION_LOOKUPS_PER_SLACK_WORKSPACE = 20

# Slack resolves its own palette keyword per client, where a hex would be a fixed choice that
# can't follow the reader's theme.
_ACCENT = "good"

_LOCATIONS: Mapping[str, str] = {
    "desktop_canvas": "On a canvas",
    "task_artifact": "On an artifact",
}

_HEADINGS: Mapping[str, str] = {
    TaskCommentActivity.Kind.MENTION: "{author} mentioned you on {link}",
    TaskCommentActivity.Kind.THREAD_REPLY: "{author} replied to your comment on {link}",
    TaskCommentActivity.Kind.OWNED_ITEM_COMMENT: "{author} commented on {link}",
}


def send_comment_slack_dms(*, team_id: int, comment_id: UUID, task_id: UUID, recipients: Mapping[int, str]) -> None:
    """DM each recipient who has not opted out, can still see the comment, and has linked Slack.

    ``recipients`` is the map ``comment_activity`` just projected: user id to activity kind.
    """
    if not recipients:
        return

    comment = Comment.objects.filter(team_id=team_id, id=comment_id, deleted=False).select_related("created_by").first()
    if comment is None:
        return _skip(comment_id, "comment_missing")
    skip_reason = _skip_reason(comment)
    if skip_reason:
        return _skip(comment_id, skip_reason)

    # Resolve preferences before the flag call so explicit opt-outs avoid its network hop.
    wanted = _recipients_wanting_dms(team_id=team_id, comment=comment, recipients=recipients)
    if not wanted:
        return _skip(comment_id, "no_enabled_recipient")

    integrations = list(
        Integration.objects.filter(team_id=team_id, kind=Integration.IntegrationKind.SLACK)
        .exclude(integration_id__isnull=True)
        .exclude(integration_id="")
        .order_by("id")
    )
    if not integrations:
        return _skip(comment_id, "no_slack_integration")
    # The flag that gates the Slack identity link itself. Gating delivery on it too means an org
    # that never had the link flow can't receive DMs, and turning it off halts delivery without a
    # deploy. Skipped in local dev, where flags evaluate against the developer's own instance and
    # the gate would otherwise fail closed on every machine — the same default-on-in-dev treatment
    # the desktop flags get.
    task = Task.objects.filter(team_id=team_id, id=task_id).only("id", "team_id", "title").first()
    if task is None:
        return _skip(comment_id, "task_missing")

    team = Team.objects.filter(id=team_id).only("id", "organization_id").first()
    if team is None:
        return _skip(comment_id, "team_missing")
    users = User.objects.in_bulk(list(wanted))
    integration_by_workspace = {integration.integration_id: integration for integration in integrations}
    slack_clients: dict[int, SlackIntegration] = {}

    def slack_for(integration: Integration) -> SlackIntegration:
        if integration.id not in slack_clients:
            slack_clients[integration.id] = SlackIntegration(integration)
        return slack_clients[integration.id]

    mention_cache: dict[tuple[int, str], str | None] = {}
    mention_lookup_allowances = {
        integration.id: _MAX_MENTION_LOOKUPS_PER_SLACK_WORKSPACE for integration in integrations
    }
    for user_id, kind in wanted.items():
        recipient = users.get(user_id)
        if recipient is None:
            _skip(comment_id, "recipient_missing", user_id=user_id)
            continue
        if not recipient.is_active:
            _skip(comment_id, "recipient_inactive", user_id=user_id)
            continue
        # Re-checked at send time rather than trusting the projected recipient set: the in-app feed
        # re-checks visibility on every read, and a DM can't be taken back.
        if not OrganizationMembership.objects.filter(organization_id=team.organization_id, user_id=user_id).exists():
            _skip(comment_id, "recipient_left_organization", user_id=user_id)
            continue
        if UserPermissions(user=recipient, team=team).current_team.effective_membership_level is None:
            _skip(comment_id, "recipient_lost_project_access", user_id=user_id)
            continue
        if not task_comment_target_is_accessible(
            team_id=team_id,
            user_id=user_id,
            task_id=task_id,
            scope=comment.scope,
            item_id=comment.item_id,
        ):
            _skip(comment_id, "recipient_lost_access", user_id=user_id)
            continue
        try:
            integration = _linked_integration_for_recipient(
                user_id=user_id, integration_by_workspace=integration_by_workspace
            )
            slack_user_id: str | None = None
            if integration is not None:
                if not settings.DEBUG and not is_slack_app_oauth_enabled(integration, integration.integration_id):
                    _skip(comment_id, "slack_app_oauth_disabled", user_id=user_id)
                    continue
                slack = slack_for(integration)
                slack_user_id = _linked_slack_user_id(user_id=user_id, integration=integration)
            else:
                email_destination_integration: Integration | None = None
                email_destination_slack: SlackIntegration | None = None
                ambiguous_email_destination = False
                for candidate in integrations:
                    if not settings.DEBUG and not is_slack_app_oauth_enabled(candidate, candidate.integration_id):
                        continue
                    candidate_slack = slack_for(candidate)
                    candidate_user_id = _slack_user_id_by_email(
                        email=recipient.email or "", integration=candidate, slack=candidate_slack
                    )
                    if not candidate_user_id:
                        continue
                    if email_destination_integration is not None:
                        ambiguous_email_destination = True
                        break
                    email_destination_integration = candidate
                    email_destination_slack = candidate_slack
                    slack_user_id = candidate_user_id
                if ambiguous_email_destination:
                    _skip(comment_id, "ambiguous_slack_workspace", user_id=user_id)
                    continue
                if email_destination_integration is not None and email_destination_slack is not None:
                    integration = email_destination_integration
                    slack = email_destination_slack

            if integration is None or not slack_user_id:
                _skip(comment_id, "recipient_not_found_in_slack", user_id=user_id)
                continue
            heading, blocks = _message(
                kind=kind,
                comment=comment,
                task=task,
                organization_id=team.organization_id,
                slack_user_id_by_email=_mention_resolver(
                    organization_id=team.organization_id,
                    integration=integration,
                    slack=slack,
                    cache=mention_cache,
                    lookup_allowances=mention_lookup_allowances,
                ),
            )
            slack.client.chat_postMessage(
                channel=slack_user_id,
                text=heading,
                attachments=[{"color": _ACCENT, "blocks": blocks}] if blocks else None,
                unfurl_links=False,
            )
        except Exception as exc:
            logger.warning("comment_slack_dm_failed", comment_id=str(comment_id), user_id=user_id, error=str(exc))


def _skip(comment_id: UUID, reason: str, user_id: int | None = None) -> None:
    """Every gate here returns silently by design, which makes "why did I get no DM" unanswerable
    without one line per exit."""
    logger.info("comment_slack_dm_skipped", comment_id=str(comment_id), reason=reason, user_id=user_id)


def _skip_reason(comment: Comment) -> str | None:
    """Replies that aren't messages. Reactions and resolve/reopen are both stored as reply
    comments, so without this a thumbs-up would DM everyone in the thread."""
    context = comment.item_context if isinstance(comment.item_context, dict) else {}
    if context.get("is_emoji"):
        return "emoji"
    if context.get("threadState"):
        return "thread_state"
    if context.get("from_slack"):
        return "from_slack"
    return None


def _recipients_wanting_dms(*, team_id: int, comment: Comment, recipients: Mapping[int, str]) -> dict[int, str]:
    """Narrow the Activity recipients to the ones who have not disabled DMs.

    ``THREAD_REPLY`` narrows further: the Activity feed notifies every thread participant, but the
    DM says "replied to your comment", so only the thread's author gets one.
    """
    enabled = {
        user_id
        for user_id, partial in User.objects.filter(id__in=list(recipients), is_active=True).values_list(
            "id", "partial_notification_settings"
        )
        if not isinstance(partial, dict)
        or partial.get(SLACK_DM_SETTING, NOTIFICATION_DEFAULTS["task_comments_slack_dm"]) is True
    }
    if not enabled:
        return {}

    root_author_id: int | None = None
    if any(kind == TaskCommentActivity.Kind.THREAD_REPLY for uid, kind in recipients.items() if uid in enabled):
        root_author_id = (
            Comment.objects.filter(team_id=team_id, id=comment.source_comment_id or comment.id)
            .values_list("created_by_id", flat=True)
            .first()
        )

    wanted: dict[int, str] = {}
    for user_id, kind in recipients.items():
        if user_id not in enabled:
            continue
        if kind == TaskCommentActivity.Kind.THREAD_REPLY and user_id != root_author_id:
            continue
        wanted[user_id] = kind
    return wanted


def _linked_slack_user_id(*, user_id: int, integration: Integration) -> str | None:
    link = (
        UserIntegration.objects.filter(
            user_id=user_id,
            kind=UserIntegration.IntegrationKind.SLACK,
            config__slack_team_id=integration.integration_id,
        )
        .order_by("-created_at")
        .first()
    )
    return link.integration_id if link else None


def _linked_integration_for_recipient(
    *, user_id: int, integration_by_workspace: Mapping[str | None, Integration]
) -> Integration | None:
    linked_workspaces = (
        UserIntegration.objects.filter(user_id=user_id, kind=UserIntegration.IntegrationKind.SLACK)
        .order_by("-created_at")
        .values_list("config__slack_team_id", flat=True)
    )
    for linked_workspace in linked_workspaces:
        if isinstance(linked_workspace, str) and (integration := integration_by_workspace.get(linked_workspace)):
            return integration
    return None


def _slack_user_id_by_email(*, email: str, integration: Integration, slack: SlackIntegration) -> str | None:
    """Match a PostHog email against the workspace's own Slack directory.

    This is what makes the feature work without every person linking an account first. It asks the
    customer's own directory a question about our own user's email, which is the opposite direction
    from the inbound path (where a Slack-supplied email would decide who a PostHog user is, and so
    can't be trusted).
    """
    workspace = integration.integration_id or ""
    if not email or not workspace:
        return None
    slack_user_id = lookup_slack_user_id_by_email(slack, integration, email)
    if not slack_user_id:
        return None
    profile = resolve_slack_user(slack.client, slack_user_id, workspace=workspace)
    # `users.lookupByEmail` also returns external Slack Connect members, whose profile emails are
    # controlled by their own workspace's admin. Without this check an outsider could claim a
    # teammate's address and receive their comment text.
    if profile.get("team_id") != workspace:
        logger.warning("comment_slack_dm_email_match_outside_workspace", integration_id=integration.id)
        return None
    return slack_user_id


def _mention_resolver(
    *,
    organization_id: str | UUID,
    integration: Integration,
    slack: SlackIntegration,
    cache: dict[tuple[int, str], str | None],
    lookup_allowances: dict[int, int],
) -> Callable[[str], str | None]:
    """Map a mentioned teammate's email to a Slack member of this workspace.

    Comment content is author-controlled, so only current organization members can reach Slack's
    email lookup. Unresolvable or untrusted addresses stay as plain display names.
    """

    def resolve(email: str) -> str | None:
        normalized_email = email.strip().lower()
        key = (integration.id, normalized_email)
        if key in cache:
            return cache[key]
        if lookup_allowances.get(integration.id, 0) <= 0:
            return None
        lookup_allowances[integration.id] -= 1
        if not OrganizationMembership.objects.filter(
            organization_id=organization_id,
            user__email__iexact=normalized_email,
            user__is_active=True,
        ).exists():
            cache[key] = None
            return None
        cache[key] = _slack_user_id_by_email(email=normalized_email, integration=integration, slack=slack)
        return cache[key]

    return resolve


def _truncate_body(body: str) -> str:
    """Cutting mid-``<…>`` leaves a link or mention token Slack renders as raw text, so a long
    comment ending in one would show `<https://posthog.com/do…` to the reader."""
    if len(body) <= _BODY_LIMIT:
        return body
    cut = body[: _BODY_LIMIT - 1]
    unclosed = cut.rfind("<")
    if unclosed > cut.rfind(">"):
        cut = cut[:unclosed]
    return cut.rstrip() + "…"


def _author_name(comment: Comment) -> str:
    author = comment.created_by
    if author is None:
        return "Someone"
    return f"{author.first_name} {author.last_name}".strip() or author.email or "Someone"


def _bridge_url(*, comment: Comment, task: Task) -> str:
    params = {"comment": str(comment.source_comment_id or comment.id)}
    if comment.scope in _LOCATIONS and comment.item_id:
        params["scope"] = comment.scope
        params["item"] = comment.item_id
    return f"{settings.SITE_URL}/code/task/{task.id}?{urlencode(params)}"


def _message(
    *,
    kind: str,
    comment: Comment,
    task: Task,
    organization_id: str | UUID | None,
    slack_user_id_by_email: Callable[[str], str | None] | None = None,
) -> tuple[str, list[dict]]:
    url = _bridge_url(comment=comment, task=task)
    title = task.title or "a task"
    author = _author_name(comment)
    template = _HEADINGS.get(kind, _HEADINGS[TaskCommentActivity.Kind.MENTION])
    # A pipe in the title would end the link label early, so it can't survive into the label.
    label = escape_slack_mrkdwn(title).replace("|", "-")
    heading = template.format(author=f"*{escape_slack_mrkdwn(author)}*", link=f"<{url}|{label}>")

    body, _ = rich_content_to_slack_payload(
        comment.rich_content,
        comment.content or "",
        include_images=False,
        organization_id=organization_id,
        slack_user_id_by_email=slack_user_id_by_email,
    )
    body = _truncate_body(body.strip())
    blocks: list[dict] = []
    if body:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
    # Three canvases in one task otherwise produce three identical headings.
    location = _LOCATIONS.get(comment.scope)
    if location:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": location}]})
    return heading, blocks
