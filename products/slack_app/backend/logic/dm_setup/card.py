"""The setup card in the PostHog DM: one message that PostHog edits in place as the person finishes steps.

The card shows the first step that is not done or skipped, with the other steps as one line each above it.
When no step is left, the card becomes the "Ready" message. Only where the message is and which steps the
person skipped get stored; each step reads its own status again when the card renders.

The per-person ``posthog-slack-dm-setup`` workflow is the only caller of ``render_dm_setup_card``, so
renders for one person never run at the same time.
"""

import structlog
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.dm_setup.link_account_step import LINK_ACCOUNT_STEP
from products.slack_app.backend.logic.dm_setup.model_step import MODEL_STEP
from products.slack_app.backend.logic.dm_setup.replies_step import REPLIES_IN_THREADS_STEP
from products.slack_app.backend.logic.dm_setup.step import DmSetupContext, DmSetupStep, DmSetupStepKey
from products.slack_app.backend.services.slack_settings import resolve_dm_setup_card, update_dm_setup_card
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

# In display order. The account link comes first, because the steps after it save settings for the linked user.
DM_SETUP_STEPS: tuple[DmSetupStep, ...] = (LINK_ACCOUNT_STEP, MODEL_STEP, REPLIES_IN_THREADS_STEP)


@frozen
class _CardContent:
    text: str
    blocks: list[dict]
    pending: tuple[DmSetupStepKey, ...]
    skipped: tuple[DmSetupStepKey, ...]
    step_count: int


def _context_line(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _ready_text(skipped_steps: list[DmSetupStep]) -> str:
    text = "*You're all set.* Two ways to start:\n• Send me a message here.\n• Mention me in a channel or a thread."
    if skipped_steps:
        titles = ", ".join(step.title for step in skipped_steps)
        text += f"\n\nYou skipped: {titles}. You can set these up later in the Home tab."
    return text


def _build_card(ctx: DmSetupContext, skipped_keys: tuple[str, ...]) -> _CardContent:
    steps = [step for step in DM_SETUP_STEPS if step.applies(ctx)]
    done = [step for step in steps if step.is_done(ctx)]
    skipped = [step for step in steps if step.skippable and step.key in skipped_keys and step not in done]
    pending = [step for step in steps if step not in done and step not in skipped]

    blocks = [_context_line(f":white_check_mark: {step.done_text}") for step in done]
    blocks += [_context_line(f"Skipped: {step.title}") for step in skipped]
    if pending:
        position = len(steps) - len(pending) + 1
        blocks.append(_context_line(f"Set up PostHog in Slack · step {position} of {len(steps)}"))
        blocks.extend(pending[0].render(ctx))
        text = "Set up PostHog in Slack"
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _ready_text(skipped)}})
        text = "PostHog is ready"
    return _CardContent(
        text=text,
        blocks=blocks,
        pending=tuple(step.key for step in pending),
        skipped=tuple(step.key for step in skipped),
        step_count=len(steps),
    )


def render_dm_setup_card(integration: WorkspaceIntegration, slack_user_id: str) -> bool:
    """Post the card the first time, then edit it in place. Returns True when nothing is left to render,
    so the workflow can stop."""
    slack_workspace_id = integration.integration_id
    state = resolve_dm_setup_card(slack_workspace_id, slack_user_id)
    if state is not None and state.completed:
        return True
    ctx = DmSetupContext(integration=integration, slack_user_id=slack_user_id)
    content = _build_card(ctx, state.skipped if state else ())
    client = SlackIntegration(integration).client

    if state is None or state.channel is None or state.ts is None:
        if not content.pending:
            # Nothing to set up, so no card. Storing that saves a workflow run on each later open of the DM.
            update_dm_setup_card(slack_workspace_id, slack_user_id, completed=True)
            return True
        response = client.chat_postMessage(channel=slack_user_id, text=content.text, blocks=content.blocks)
        update_dm_setup_card(
            slack_workspace_id,
            slack_user_id,
            channel=str(response["channel"]),
            ts=str(response["ts"]),
            completed=False,
        )
        # pinned: analytics event and property names, renaming breaks dashboards
        capture_slack_event(
            integration,
            "slack app dm setup card shown",
            slack_user_id=slack_user_id,
            pending_steps=[str(key) for key in content.pending],
            step_count=content.step_count,
        )
        return False

    try:
        client.chat_update(channel=state.channel, ts=state.ts, text=content.text, blocks=content.blocks)
    except SlackApiError:
        logger.warning("slack_app_dm_setup_card_update_failed", slack_user_id=slack_user_id, exc_info=True)
        return False
    if content.pending:
        return False
    update_dm_setup_card(slack_workspace_id, slack_user_id, completed=True)
    # pinned: analytics event and property names, renaming breaks dashboards
    capture_slack_event(
        integration,
        "slack app dm setup completed",
        slack_user_id=slack_user_id,
        step_count=content.step_count,
        skipped_steps=[str(key) for key in content.skipped],
    )
    return True
