"""Shared helpers used across PostHog Slack App Temporal activities.

These helpers exist outside the activity modules so that any activity in
``slack_app.activities.*`` can use them without forcing a cross-module import
between activity files.
"""

from typing import TYPE_CHECKING, Any

from slack_sdk.errors import SlackApiError

if TYPE_CHECKING:
    from products.tasks.backend.facade.contracts import PersonalGitHubRepoAccess


def block_if_team_over_quota(
    *,
    integration: Any,
    slack: Any,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    context: str,
    post_denial: bool = True,
) -> bool:
    """Refuse a Slack-bot turn when the team is over its AI credits quota.

    The user-facing denial message lives in ``products.slack_app.backend.api``
    next to the Slack-posting helpers, while the quota lookup lives here so
    activity modules can compose both without each one re-importing
    ``ee.billing``. Returns True when the team was blocked. Pass
    ``post_denial=False`` for a turn nobody asked PostHog for, so the refusal
    stops the run without a message in the thread.
    """
    from products.slack_app.backend.api import post_quota_exhausted_denial

    from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

    if not is_team_limited(
        integration.team.api_token,
        QuotaResource.AI_CREDITS,
        QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
    ):
        return False

    if post_denial:
        post_quota_exhausted_denial(
            integration=integration,
            slack=slack,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            context=context,
        )
    return True


def block_if_ai_processing_not_approved(
    *,
    integration: Any,
    slack: Any,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    context: str,
    post_denial: bool = True,
) -> bool:
    """Refuse a Slack-bot turn when the organization has not approved AI data processing.

    Every turn sends Slack content to external AI services, so it needs the same org
    consent as PostHog AI in the web app. A null consent counts as not approved, as in
    the settings toggle. Returns True when the turn was blocked.
    """
    from products.slack_app.backend.api import post_ai_processing_not_approved_denial

    if integration.team.organization.is_ai_data_processing_approved:
        return False

    if post_denial:
        post_ai_processing_not_approved_denial(
            integration=integration,
            slack=slack,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            context=context,
        )
    return True


def post_personal_github_prompt(
    *,
    slack: Any,
    channel: str,
    thread_ts: str,
    team_id: int,
    user_id: int,
    access: "PersonalGitHubRepoAccess",
    repository: str | None = None,
    task_started: bool = False,
    ephemeral_to: str | None = None,
) -> None:
    """Tell the user what is wrong with their personal GitHub connection, with buttons to fix it.

    ``ephemeral_to`` names a Slack user who alone sees the prompt; without it the prompt is a
    thread reply everyone can read.

    ``task_started`` picks the wording: True warns about a task that runs anyway, False
    explains a task that was held. Every reason links to the personal integrations settings
    page. Missing repo access also links to the GitHub App install page, where GitHub lets
    the user add repositories to an installation that already exists.
    """
    import structlog
    from rest_framework.exceptions import ValidationError as ApiValidationError

    from posthog.api.github_callback.types import github_app_install_url_shareable

    from products.slack_app.backend.services.slack_messages import (
        personal_integrations_url,
        post_slack_ephemeral,
        post_slack_thread_reply,
    )
    from products.tasks.backend.facade.contracts import PersonalGitHubRepoAccess

    settings_url = personal_integrations_url(team_id)
    buttons: list[dict[str, Any]] = []
    if access == PersonalGitHubRepoAccess.NO_REPO_ACCESS:
        text = (
            f"Your personal GitHub connection can't access `{repository}`, so I might not be able to "
            "clone it or open a pull request as you. To fix this, give the PostHog GitHub app access "
            "to this repository."
        )
        try:
            buttons.append(_link_button("Manage repository access", github_app_install_url_shareable(), primary=True))
        except ApiValidationError:
            pass
        buttons.append(_link_button("Check connection", settings_url, primary=not buttons))
    elif access == PersonalGitHubRepoAccess.NEEDS_RECONNECT and task_started:
        text = (
            "Your personal GitHub connection has expired, so I might not be able to clone the "
            "repository or open a pull request as you. To fix this, reconnect it."
        )
        buttons.append(_link_button("Reconnect GitHub", settings_url, primary=True))
    elif access == PersonalGitHubRepoAccess.NEEDS_RECONNECT:
        text = (
            "I can't start this task. Your personal GitHub connection has expired, so I can't open "
            "the pull request as you. Reconnect it, then mention me again."
        )
        buttons.append(_link_button("Reconnect GitHub", settings_url, primary=True))
    else:
        text = (
            "I can't start this task yet. You haven't connected your personal GitHub, so I can't open "
            "the pull request as you. Connect it, then mention me again."
        )
        buttons.append(_link_button("Connect GitHub", settings_url, primary=True))

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": buttons},
    ]
    if ephemeral_to:
        post_slack_ephemeral(
            slack.client, channel=channel, user=ephemeral_to, thread_ts=thread_ts, text=text, blocks=blocks
        )
    else:
        post_slack_thread_reply(slack.client, channel=channel, thread_ts=thread_ts, text=text, blocks=blocks)
    structlog.get_logger(__name__).info(
        "slack_app_personal_github_prompt_posted",
        user_id=user_id,
        team_id=team_id,
        channel=channel,
        thread_ts=thread_ts,
        reason=str(access),
        repository=repository,
        task_started=task_started,
    )


def _link_button(label: str, url: str, *, primary: bool) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": label, "emoji": True},
        "url": url,
    }
    if primary:
        button["style"] = "primary"
    return button


def warn_if_personal_github_cannot_open_repository(
    *,
    slack: Any,
    channel: str,
    thread_ts: str,
    team_id: int,
    user_id: int,
    slack_user_id: str,
    repository: str,
) -> None:
    """Warn the user, and only them, when their personal GitHub connection exists but can't open the repo.

    Slack tasks author pull requests as the user, so a revoked token or a repository outside
    the user's installation makes the run fail later with an unclear error. The task still
    runs, because it can do useful work without the repository. A user with no connection
    gets no warning. Errors in the check or the post are logged and never fail the caller.
    """
    import structlog

    from products.tasks.backend.facade import api as tasks_facade
    from products.tasks.backend.facade.contracts import PersonalGitHubRepoAccess

    try:
        access = tasks_facade.check_personal_github_repo_access(user_id, repository)
        if access not in (PersonalGitHubRepoAccess.NEEDS_RECONNECT, PersonalGitHubRepoAccess.NO_REPO_ACCESS):
            return
        post_personal_github_prompt(
            slack=slack,
            channel=channel,
            thread_ts=thread_ts,
            team_id=team_id,
            user_id=user_id,
            access=access,
            repository=repository,
            task_started=True,
            ephemeral_to=slack_user_id,
        )
    except Exception:
        structlog.get_logger(__name__).exception(
            "slack_app_personal_github_repo_access_warning_failed",
            user_id=user_id,
            team_id=team_id,
            repository=repository,
        )


# Reaction errors that should never abort a follow-up activity — the 👀/🔍 reaction is purely
# cosmetic UX feedback, so a deleted/unreachable message or a missing reaction is a no-op.
_BENIGN_REACTION_ERRORS = frozenset({"already_reacted", "message_not_found", "no_reaction", "cant_react"})


def safe_react(client: Any, channel: str, timestamp: str, name: str) -> None:
    try:
        client.reactions_add(channel=channel, timestamp=timestamp, name=name)
    except SlackApiError as e:
        if e.response.get("error") in _BENIGN_REACTION_ERRORS:
            pass
        else:
            raise


def safe_unreact(client: Any, channel: str, timestamp: str, name: str) -> None:
    """Remove a reaction; a missing reaction or message is a no-op."""
    try:
        client.reactions_remove(channel=channel, timestamp=timestamp, name=name)
    except Exception:
        pass


def swap_reaction(client: Any, channel: str, timestamp: str, remove: str, add: str) -> None:
    """Replace one reaction with another; a missing old reaction is a no-op."""
    safe_unreact(client, channel, timestamp, remove)
    safe_react(client, channel, timestamp, add)
