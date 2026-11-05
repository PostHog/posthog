"""The setup card in the PostHog DM: one message that PostHog edits in place as the person finishes steps.

The card shows the first step that is not done, with the done steps as one line each above it. When no
step is left, the card becomes the "Ready" message. Only where the message is gets stored; each step
reads its own status again when the card renders.
"""

from django.core.cache import cache

import structlog
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_slack_app_dm_setup_card_enabled
from products.slack_app.backend.logic.dm_setup.link_account_step import LINK_ACCOUNT_STEP
from products.slack_app.backend.logic.dm_setup.step import DmSetupContext, DmSetupStep, DmSetupStepKey
from products.slack_app.backend.services.slack_settings import (
    DmSetupCardState,
    resolve_dm_setup_card,
    set_dm_setup_card,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

# In display order.
DM_SETUP_STEPS: tuple[DmSetupStep, ...] = (LINK_ACCOUNT_STEP,)

# Slack sends one app_home_opened event for each open of the DM, and two can arrive together.
POST_LOCK_SECONDS = 30


@frozen
class _CardContent:
    text: str
    blocks: list[dict]
    pending: tuple[DmSetupStepKey, ...]
    step_count: int


def _build_card(ctx: DmSetupContext) -> _CardContent:
    steps = [step for step in DM_SETUP_STEPS if step.applies(ctx)]
    done = [step for step in steps if step.is_done(ctx)]
    pending = [step for step in steps if step not in done]

    blocks: list[dict] = [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f":white_check_mark: {step.done_text}"}]}
        for step in done
    ]
    if pending:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Set up PostHog in Slack · step {len(done) + 1} of {len(steps)}"}
                ],
            }
        )
        blocks.extend(pending[0].render(ctx))
        text = "Set up PostHog in Slack"
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*You're all set.* Two ways to start:\n"
                    "• Send me a message here.\n"
                    "• Mention me in a channel or a thread.",
                },
            }
        )
        text = "PostHog is ready"
    return _CardContent(text=text, blocks=blocks, pending=tuple(step.key for step in pending), step_count=len(steps))


def _update_card(ctx: DmSetupContext, state: DmSetupCardState) -> None:
    content = _build_card(ctx)
    try:
        SlackIntegration(ctx.integration).client.chat_update(
            channel=state.channel, ts=state.ts, text=content.text, blocks=content.blocks
        )
    except SlackApiError:
        logger.warning("slack_app_dm_setup_card_update_failed", slack_user_id=ctx.slack_user_id, exc_info=True)
        return
    if not content.pending:
        slack_workspace_id = ctx.integration.integration_id
        set_dm_setup_card(
            slack_workspace_id,
            ctx.slack_user_id,
            DmSetupCardState(channel=state.channel, ts=state.ts, completed=True),
        )
        # pinned: analytics event name, renaming breaks dashboards
        capture_slack_event(
            ctx.integration,
            "slack app dm setup completed",
            slack_user_id=ctx.slack_user_id,
            step_count=content.step_count,
        )


def _post_card(ctx: DmSetupContext) -> None:
    slack_workspace_id = ctx.integration.integration_id
    lock_key = f"slack_app:dm_setup_card:posting:{slack_workspace_id}:{ctx.slack_user_id}"
    if not cache.add(lock_key, 1, POST_LOCK_SECONDS):
        return
    try:
        # A request that waited for the lock finds the card that the first request posted.
        if resolve_dm_setup_card(slack_workspace_id, ctx.slack_user_id) is not None:
            return
        content = _build_card(ctx)
        # People who have nothing left to set up get no card.
        if not content.pending:
            return
        response = SlackIntegration(ctx.integration).client.chat_postMessage(
            channel=ctx.slack_user_id, text=content.text, blocks=content.blocks
        )
        set_dm_setup_card(
            slack_workspace_id,
            ctx.slack_user_id,
            DmSetupCardState(channel=str(response["channel"]), ts=str(response["ts"]), completed=False),
        )
        # pinned: analytics event and property names, renaming breaks dashboards
        capture_slack_event(
            ctx.integration,
            "slack app dm setup card shown",
            slack_user_id=ctx.slack_user_id,
            pending_steps=[str(key) for key in content.pending],
            step_count=content.step_count,
        )
    finally:
        cache.delete(lock_key)


def show_dm_setup_card(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    """Run when the person opens the PostHog DM. Posts the card the first time, then renders it again,
    which keeps its link fresh and catches steps done somewhere else."""
    ctx = DmSetupContext(integration=integration, slack_user_id=slack_user_id)
    state = resolve_dm_setup_card(integration.integration_id, slack_user_id)
    if state is None:
        if is_slack_app_dm_setup_card_enabled(integration):
            _post_card(ctx)
    elif not state.completed:
        _update_card(ctx, state)


def refresh_dm_setup_card(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    """Run after a step is done outside the card, for example after the account link in the browser."""
    state = resolve_dm_setup_card(integration.integration_id, slack_user_id)
    if state is not None and not state.completed:
        _update_card(DmSetupContext(integration=integration, slack_user_id=slack_user_id), state)
