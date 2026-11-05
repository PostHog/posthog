"""The setup thread in the PostHog DM.

The top message shows the progress and is edited in place. Each step is a new reply in the thread, so the
person gets a notification for it, and a finished step reply shrinks to one line without buttons. A last
"Ready" reply closes the setup. Only the message timestamps, the shown progress, the skipped steps and the
finished state get stored; each step reads its own status again on every plan.

The per-person ``posthog-slack-dm-setup`` workflow calls these functions through activities: one plan,
then its edits, then at most one post. Renders for one person therefore never run at the same time.
"""

from dataclasses import replace

from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.dm_setup.link_account_step import LINK_ACCOUNT_STEP
from products.slack_app.backend.logic.dm_setup.model_step import MODEL_STEP
from products.slack_app.backend.logic.dm_setup.replies_step import REPLIES_IN_THREADS_STEP
from products.slack_app.backend.logic.dm_setup.step import DmSetupContext, DmSetupStep
from products.slack_app.backend.services.slack_settings import resolve_dm_setup_card, update_dm_setup_card
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration
from products.slack_app.backend.temporal.types import SlackDmSetupMessage, SlackDmSetupPlan

# In display order. The account link comes first, because the steps after it save settings for the linked user.
DM_SETUP_STEPS: tuple[DmSetupStep, ...] = (LINK_ACCOUNT_STEP, MODEL_STEP, REPLIES_IN_THREADS_STEP)

# pinned: analytics event names, renaming breaks dashboards
SETUP_STARTED_EVENT = "slack app dm setup started"
STEP_SHOWN_EVENT = "slack app dm setup step shown"
SETUP_COMPLETED_EVENT = "slack app dm setup completed"

_NOTHING_TO_DO = SlackDmSetupPlan(edits=[], post=None, finished=True, plan_again=False)


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _root_message(progress: str, *, ready: bool, ts: str | None = None) -> SlackDmSetupMessage:
    if ready:
        title = "*PostHog is set up*\nThe steps are in this thread."
    else:
        title = "*Set up PostHog in Slack*\nI'll take you through a few short steps in this thread."
    return SlackDmSetupMessage(
        kind="root",
        text="PostHog is set up" if ready else "Set up PostHog in Slack",
        blocks=[_section(title), _context(progress)],
        ts=ts,
        progress=progress,
    )


def _step_message(ctx: DmSetupContext, step: DmSetupStep, position: int, total: int) -> SlackDmSetupMessage:
    # The mention makes the person follow the thread, so each new step reply notifies them.
    return SlackDmSetupMessage(
        kind="step",
        step=step.key,
        text=f"Step {position} of {total}: {step.title}",
        blocks=[_context(f"<@{ctx.slack_user_id}> Step {position} of {total}"), *step.render(ctx)],
    )


def _summary_message(step: DmSetupStep, ts: str, *, skipped: bool) -> SlackDmSetupMessage:
    line = f"Skipped: {step.title}" if skipped else f":white_check_mark: {step.done_text}"
    return SlackDmSetupMessage(
        kind="step", step=step.key, text=line, blocks=[_context(line)], ts=ts, summarizes_step=True
    )


def _ready_message(ctx: DmSetupContext, skipped: list[DmSetupStep]) -> SlackDmSetupMessage:
    text = (
        f"<@{ctx.slack_user_id}> *You're all set.* Two ways to start:\n"
        "• Send me a direct message.\n"
        "• Mention me in a channel or a thread."
    )
    if skipped:
        titles = ", ".join(step.title for step in skipped)
        text += f"\n\nYou skipped: {titles}. You can set these up later in the Home tab."
    return SlackDmSetupMessage(kind="ready", text="PostHog is ready", blocks=[_section(text)])


def plan_dm_setup(integration: WorkspaceIntegration, slack_user_id: str) -> SlackDmSetupPlan:
    """Decide what one refresh changes. Reads only, except that it stores "nothing to set up"."""
    slack_workspace_id = integration.integration_id
    state = resolve_dm_setup_card(slack_workspace_id, slack_user_id)
    if state is not None and state.completed:
        return _NOTHING_TO_DO

    ctx = DmSetupContext(integration=integration, slack_user_id=slack_user_id)
    steps = [step for step in DM_SETUP_STEPS if step.applies(ctx)]
    done = [step for step in steps if step.is_done(ctx)]
    skipped_keys = state.skipped if state else ()
    skipped = [step for step in steps if step.skippable and step.key in skipped_keys and step not in done]
    pending = [step for step in steps if step not in done and step not in skipped]
    progress = f"{len(steps) - len(pending)} of {len(steps)} steps done"

    if state is None or state.root_ts is None:
        if not pending:
            # Nothing to set up, so no thread. Storing that saves a workflow run on each later open of the DM.
            update_dm_setup_card(slack_workspace_id, slack_user_id, completed=True)
            return _NOTHING_TO_DO
        return SlackDmSetupPlan(edits=[], post=_root_message(progress, ready=False), finished=False, plan_again=True)

    edits = [
        _summary_message(step, state.step_ts[step.key], skipped=step in skipped)
        for step in [*done, *skipped]
        if step.key in state.step_ts and step.key not in state.summarized
    ]
    if not pending:
        edits.append(_root_message(progress, ready=True, ts=state.root_ts))
        return SlackDmSetupPlan(edits=edits, post=_ready_message(ctx, skipped), finished=True, plan_again=False)

    if state.progress != progress:
        edits.append(_root_message(progress, ready=False, ts=state.root_ts))
    current = _step_message(ctx, pending[0], len(steps) - len(pending) + 1, len(steps))
    current_ts = state.step_ts.get(current.step or "")
    if current_ts is None:
        return SlackDmSetupPlan(edits=edits, post=current, finished=False, plan_again=False)
    # Rendering the shown step again keeps its content fresh, such as the 15-minute account link.
    edits.append(replace(current, ts=current_ts))
    return SlackDmSetupPlan(edits=edits, post=None, finished=False, plan_again=False)


def post_dm_setup_message(integration: WorkspaceIntegration, slack_user_id: str, message: SlackDmSetupMessage) -> None:
    slack_workspace_id = integration.integration_id
    state = resolve_dm_setup_card(slack_workspace_id, slack_user_id)
    client = SlackIntegration(integration).client
    if message.kind == "root":
        response = client.chat_postMessage(channel=slack_user_id, text=message.text, blocks=message.blocks)
        update_dm_setup_card(
            slack_workspace_id,
            slack_user_id,
            root=(str(response["channel"]), str(response["ts"])),
            progress=message.progress,
        )
        capture_slack_event(integration, SETUP_STARTED_EVENT, slack_user_id=slack_user_id)
        return

    if state is None or state.channel is None or state.root_ts is None:
        raise ValueError("A setup reply needs the top message of the thread")
    response = client.chat_postMessage(
        channel=state.channel, thread_ts=state.root_ts, text=message.text, blocks=message.blocks
    )
    if message.kind == "step" and message.step:
        update_dm_setup_card(slack_workspace_id, slack_user_id, step_ts=(message.step, str(response["ts"])))
        capture_slack_event(integration, STEP_SHOWN_EVENT, slack_user_id=slack_user_id, step=message.step)
    elif message.kind == "ready":
        update_dm_setup_card(slack_workspace_id, slack_user_id, completed=True)
        capture_slack_event(
            integration, SETUP_COMPLETED_EVENT, slack_user_id=slack_user_id, skipped_steps=list(state.skipped)
        )


def edit_dm_setup_message(integration: WorkspaceIntegration, slack_user_id: str, message: SlackDmSetupMessage) -> None:
    """Edit one message in place. Slack sends no notification for an edit."""
    slack_workspace_id = integration.integration_id
    state = resolve_dm_setup_card(slack_workspace_id, slack_user_id)
    if state is None or state.channel is None or message.ts is None:
        return
    SlackIntegration(integration).client.chat_update(
        channel=state.channel, ts=message.ts, text=message.text, blocks=message.blocks
    )
    if message.kind == "root" and message.progress:
        update_dm_setup_card(slack_workspace_id, slack_user_id, progress=message.progress)
    if message.summarizes_step and message.step:
        update_dm_setup_card(slack_workspace_id, slack_user_id, summarized_step=message.step)
