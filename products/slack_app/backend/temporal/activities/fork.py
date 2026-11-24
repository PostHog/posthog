"""The activity behind the fork menu under a reply.

Lives apart from the workflow, like every other Slack-app activity. See
``products.slack_app.backend.temporal.slack_app_fork`` for what a fork is.
"""

from typing import Any

import structlog
from temporalio import activity

from products.slack_app.backend.services.slack_conversations import channel_is_ext_shared
from products.slack_app.backend.temporal.types import SlackAppForkThreadInputs

logger = structlog.get_logger(__name__)

# Long enough to recognise the thread, short enough to stay one line in the seed message.
_TITLE_LIMIT = 120

_SEED_UNAVAILABLE = (
    "I couldn't set that up. You don't seem to have a PostHog account matching your Slack email, "
    "or your projects have no connected repo."
)


@activity.defn
def process_slack_app_fork_thread_activity(inputs: SlackAppForkThreadInputs) -> None:
    process_slack_app_fork_thread_payload(inputs.payload, target_channel=inputs.target_channel)


def _ephemeral(slack: Any, text: str, *, channel: str, thread_ts: str, user: str, response_url: str | None) -> None:
    """Answer whoever asked, and only them.

    Forking must leave no trace in the source thread, so every outcome, including
    refusals, goes through here. A fork into a channel shows up in the destination
    channel only.

    An ephemeral post is preferred: it lands in the thread the reader is looking at and
    cannot disturb the message the menu hangs off. ``response_url`` is the fallback for
    a channel the bot isn't in, with ``replace_original`` pinned false, because a reply to
    an interactive message otherwise overwrites the message carrying the control, which
    here is the agent's own answer.
    """
    from products.slack_app.backend.api import (
        _post_slack_user_ephemeral,  # noqa: PLC0415 — products import, deferred like the rest
    )

    if _post_slack_user_ephemeral(slack, channel, user, thread_ts, text):
        return
    if not response_url:
        return
    import requests  # noqa: PLC0415 — keeps the HTTP dep off the module import path

    try:
        requests.post(
            response_url,
            json={"response_type": "ephemeral", "replace_original": False, "text": text},
            timeout=5,
        )
    except requests.RequestException:
        logger.warning("slack_app_fork_ephemeral_failed")


def process_slack_app_fork_thread_payload(payload: dict[str, Any], *, target_channel: str | None = None) -> None:
    """Start a task that continues the forked thread, in the clicker's DM or in ``target_channel``.

    The task gets a link to the thread, not a copy of it. The agent reads the thread
    through the clicker's Slack MCP, with the clicker's own Slack access, so a fork
    needs that connection.
    """
    from posthog.models.integration import SlackIntegration

    from products.mcp_store.backend.facade.api import has_slack_mcp_connected
    from products.slack_app.backend.analytics import capture_slack_event
    from products.slack_app.backend.api import SLACK_INTEGRATION_KIND, _channel_is_approved, _start_mention_workflow
    from products.slack_app.backend.facade.constants import PUBLIC_CHANNEL_CONVERSATION_TYPES
    from products.slack_app.backend.feature_flags import is_slack_app_forking_enabled
    from products.slack_app.backend.logic.feature_tips.features import SlackFeature
    from products.slack_app.backend.logic.feature_tips.state import record_feature_used
    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.slack_app.backend.services.integration_resolver import load_integrations, resolve_user_for_workspace
    from products.slack_app.backend.services.slack_conversations import resolve_conversation_type
    from products.slack_app.backend.services.slack_messages import context_block, project_web_url, thread_permalink

    source_channel = payload.get("channel", {}).get("id")
    message = payload.get("message", {}) or {}
    # Forking a reply forks the discussion it belongs to, not the single message:
    # "sidebar off this" always means the thread.
    source_thread_ts = message.get("thread_ts") or message.get("ts")
    # The reply the menu hangs off, so the agent knows how far the reader had read.
    source_message_ts = message.get("ts") or source_thread_ts
    slack_user_id = payload.get("user", {}).get("id")
    slack_team_id = payload.get("team", {}).get("id")
    response_url = payload.get("response_url")

    if not (source_channel and source_thread_ts and slack_user_id and slack_team_id):
        logger.warning(
            "slack_app_fork_missing_payload_fields",
            has_channel=bool(source_channel),
            has_thread_ts=bool(source_thread_ts),
            has_user=bool(slack_user_id),
            has_team=bool(slack_team_id),
        )
        return

    logger.info(
        "slack_app_fork_requested",
        slack_team_id=slack_team_id,
        source_channel=source_channel,
        source_thread_ts=source_thread_ts,
        to_channel=bool(target_channel),
    )

    workspace_result = load_integrations(
        slack_team_id=slack_team_id,
        kinds=[SLACK_INTEGRATION_KIND],
        slack_user_id=slack_user_id,
        channel=source_channel,
        thread_ts=source_thread_ts,
    )
    if not workspace_result.candidates:
        logger.info("slack_app_fork_refused", reason="no_candidates", slack_team_id=slack_team_id)
        return

    probe = workspace_result.resolved_or_first()
    # Every reply to the asker goes to the source thread, ephemerally. Built off the
    # probe so refusals before project resolution can still answer them.
    reply_to = {
        "channel": source_channel,
        "thread_ts": source_thread_ts,
        "user": slack_user_id,
        "response_url": response_url,
    }
    if probe is None or not is_slack_app_forking_enabled(probe):
        # Outside the rollout the menu is inert rather than apologetic, so a
        # workspace that never opted in does not learn the feature exists.
        logger.info("slack_app_fork_refused", reason="flag_off", slack_team_id=slack_team_id)
        return

    # The fork runs as whoever clicked, against a project *they* can reach, never
    # inherited from the source thread's original mentioner.
    resolution = resolve_user_for_workspace(
        workspace_result=workspace_result,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
    )
    integration = resolution.integration or (resolution.candidates[0] if len(resolution.candidates) == 1 else None)
    if resolution.user is None or integration is None:
        logger.info(
            "slack_app_fork_refused",
            reason="user_unresolved" if resolution.user is None else "no_single_project",
            slack_team_id=slack_team_id,
        )
        _ephemeral(SlackIntegration(probe), _SEED_UNAVAILABLE, **reply_to)
        return

    slack = SlackIntegration(integration)

    if not has_slack_mcp_connected(integration.team_id, resolution.user.id):
        logger.info("slack_app_fork_refused", reason="no_slack_mcp", slack_team_id=slack_team_id)
        _ephemeral(
            slack,
            "To fork a thread, connect the Slack MCP server in PostHog first. It lets me read the thread "
            f"with your Slack access. <{project_web_url(integration.team_id)}/mcp-servers|Connect it here>, "
            "then fork again.",
            **reply_to,
        )
        return

    # A DM is never externally shared, so forking would otherwise launder content out
    # of a Slack Connect channel and past the approval gate that keeps customer-facing
    # writes gated. Refuse rather than fork-and-discover-later, and carry the flag
    # onto the run so the destination inherits the source's posture.
    is_ext_shared = channel_is_ext_shared(slack, source_channel)
    if is_ext_shared and not _channel_is_approved(slack_team_id, source_channel):
        logger.info("slack_app_fork_refused", reason="ext_shared_unapproved", slack_team_id=slack_team_id)
        _ephemeral(
            slack,
            "This is a Slack Connect channel that hasn't been approved for PostHog yet. "
            "`@PostHog` in the channel to approve it first, then fork.",
            **reply_to,
        )
        return

    if target_channel:
        # The channel picker only offers public channels. Only a thread that everyone in the
        # workspace can already read may move into one, so a private channel, a DM or a
        # Slack Connect channel never reaches a wider audience through a fork.
        source_is_public = (
            not is_ext_shared
            and resolve_conversation_type(slack, {}, source_channel) in PUBLIC_CHANNEL_CONVERSATION_TYPES
        )
        if not source_is_public:
            logger.info("slack_app_fork_refused", reason="source_not_public", slack_team_id=slack_team_id)
            _ephemeral(
                slack,
                'Only threads in public channels can be forked to a channel. Use "Fork to DM" to continue '
                "this one in private.",
                **reply_to,
            )
            return
        if not _join_channel(slack, target_channel):
            logger.info("slack_app_fork_refused", reason="target_not_joinable", slack_team_id=slack_team_id)
            _ephemeral(
                slack,
                f"I can't post in <#{target_channel}>. Invite `@PostHog` to that channel, then fork again.",
                **reply_to,
            )
            return

    # A thread the agent has already worked in has a task behind it, holding far more
    # than the messages did: prior runs, session logs, artifacts, the PR. Its id goes to
    # the fork so the agent can read that task. Its repository is deliberately not
    # carried over: the fork runs the normal cascade, which resolves a repo against what
    # the *requester* can access rather than what the source thread's mentioner could.
    source_task = (
        SlackThreadTaskMapping.objects.filter(
            integration_id=integration.id,
            channel=source_channel,
            thread_ts=source_thread_ts,
        )
        .values_list("task_id", flat=True)
        .first()
    )
    source_task_id = str(source_task) if source_task else None

    permalink = thread_permalink(slack, source_channel, source_thread_ts)
    title = _fork_title(_read_thread_root(slack, source_channel, source_thread_ts) or {})
    thread_link = f"<{permalink}|this thread>" if permalink else "a thread"
    origin = f"Forked from {thread_link} in <#{source_channel}>"
    if target_channel:
        origin = f"{origin} by <@{slack_user_id}>"
    if source_task_id:
        origin = f"{origin} · <{project_web_url(integration.team_id)}/tasks/{source_task_id}|Original task>"
    body = "I'm reading the thread and continuing from where it stopped."
    seed_blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f":thread: *{title}*\n{body}"}},
        context_block(origin),
    ]
    destination = target_channel or slack_user_id

    try:
        seed = slack.client.chat_postMessage(
            channel=destination,
            text=f"{title}: {body}",
            blocks=seed_blocks,
            unfurl_links=False,
        )
    except Exception:
        logger.exception("slack_app_fork_seed_post_failed", slack_team_id=slack_team_id)
        failure = (
            f"I couldn't post in <#{target_channel}>. Check that `@PostHog` is in that channel, then try again."
            if target_channel
            else "I couldn't open a DM. Check that you allow DMs from apps, then try again."
        )
        _ephemeral(slack, failure, **reply_to)
        return

    dest_channel = seed.get("channel")
    seed_ts = seed.get("ts")
    if not (dest_channel and seed_ts):
        logger.warning("slack_app_fork_seed_missing_ids", slack_team_id=slack_team_id)
        return

    # The run answers in the seed's thread, so that thread owns the task, the mapping and
    # every follow-up. The event stands in for the request a person would have typed there.
    fork_event = {
        "type": "message",
        "channel": dest_channel,
        "channel_type": "channel" if target_channel else "im",
        "user": slack_user_id,
        "ts": seed_ts,
        "thread_ts": seed_ts,
        "text": f"Fork: {title}",
    }
    _start_mention_workflow(
        fork_event,
        integration,
        slack_team_id,
        None,
        posthog_user=resolution.user,
        is_ext_shared_channel=is_ext_shared,
        fork_source_channel=source_channel,
        fork_source_thread_ts=source_thread_ts,
        fork_source_message_ts=source_message_ts,
        fork_source_task_id=source_task_id,
    )

    logger.info(
        "slack_app_fork_created",
        slack_team_id=slack_team_id,
        team_id=integration.team_id,
        source_channel=source_channel,
        dest_channel=dest_channel,
        has_source_task=bool(source_task_id),
    )
    if target_channel:
        confirmation = f":thread: Forked to <#{target_channel}>. Only you can see this."
    else:
        confirmation = (
            ":envelope_with_arrow: Forked to your DMs. Check your messages with PostHog. Only you can see this."
        )
    _ephemeral(slack, confirmation, **reply_to)

    # Reported as its own event rather than folded into the mention funnel: a fork is a
    # different intent and would otherwise inflate mention counts.
    record_feature_used(slack_team_id, slack_user_id, SlackFeature.FORK_THREAD)
    capture_slack_event(
        integration,
        "slack app fork created",
        slack_user_id=slack_user_id,
        source_channel=source_channel,
        destination="channel" if target_channel else "dm",
        is_ext_shared_channel=is_ext_shared,
        has_source_task=bool(source_task_id),
    )


def _join_channel(slack: Any, channel: str) -> bool:
    """Whether the bot is in ``channel`` after this call, so the seed message can be posted there.

    ``conversations.join`` needs ``channels:join``, which an install from before that
    scope does not hold. Joining a channel the bot is already in succeeds.
    """
    try:
        return bool(slack.client.conversations_join(channel=channel).get("ok"))
    except Exception:
        logger.info("slack_app_fork_channel_join_failed", channel=channel)
        return False


def _read_thread_root(slack: Any, channel: str, thread_ts: str) -> dict[str, Any] | None:
    """The forked thread's opening message, or `None` if the bot can't read the thread.

    Only names the seed message and the task. The agent reads the thread itself through
    the Slack MCP, so an unreadable root costs the fork its title and nothing else.
    """
    try:
        response = slack.client.conversations_replies(channel=channel, ts=thread_ts, limit=1)
    except Exception:
        logger.info("slack_app_fork_thread_unreadable", channel=channel, thread_ts=thread_ts)
        return None
    messages = response.get("messages") or []
    return messages[0] if messages else {}


def _fork_title(root: dict[str, Any]) -> str:
    """A one-line name for the thread, taken from the message that opened it.

    The seed message needs to say *which* discussion it forked, and at this point no task
    exists to borrow a title from. The opening message is what a reader would recognise
    the thread by.

    Falls back to a generic label for a thread that opens with a file, an image, or a
    bare mention: better an unhelpful title than an empty one.
    """
    from products.slack_app.backend.services.slack_messages import (  # noqa: PLC0415 — products import, deferred like the rest
        extract_message_text,
        labeled_mentions_to_display_names,
    )

    try:
        text = extract_message_text(root)
    except Exception:
        text = (root.get("text") or "").strip()
    first_line = next(
        (line.strip() for line in labeled_mentions_to_display_names(text).splitlines() if line.strip()), ""
    )
    if not first_line:
        return "Slack thread"
    return first_line if len(first_line) <= _TITLE_LIMIT else first_line[: _TITLE_LIMIT - 1].rstrip() + "…"
