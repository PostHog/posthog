"""Only the per-person workflow calls these, through activities, so renders for one person never overlap."""

from dataclasses import replace

from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.dm_setup.step import DmSetupContext, DmSetupStep
from products.slack_app.backend.logic.dm_setup.steps import DM_SETUP_STEPS
from products.slack_app.backend.services.slack_messages import context_block, section_block
from products.slack_app.backend.services.slack_settings import resolve_dm_setup_card, update_dm_setup_card
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration
from products.slack_app.backend.temporal.types import DM_SETUP_DONE_PLAN, SlackDmSetupMessage, SlackDmSetupPlan

# pinned: analytics event names, renaming breaks dashboards
SETUP_STARTED_EVENT = "slack app dm setup started"
STEP_SHOWN_EVENT = "slack app dm setup step shown"
SETUP_COMPLETED_EVENT = "slack app dm setup completed"


def _root_message(progress: str, *, ready: bool, ts: str | None = None) -> SlackDmSetupMessage:
    if ready:
        title = "*PostHog is set up*\nThe steps are in this thread."
    else:
        title = "*Set up PostHog in Slack*\nI'll take you through a few short steps in this thread."
    return SlackDmSetupMessage(
        kind="root",
        text="PostHog is set up" if ready else "Set up PostHog in Slack",
        blocks=[section_block(title), context_block(progress)],
        ts=ts,
        progress=progress,
    )


def _step_message(ctx: DmSetupContext, step: DmSetupStep, position: int, total: int) -> SlackDmSetupMessage:
    # The mention makes the person follow the thread, so each new step reply notifies them.
    return SlackDmSetupMessage(
        kind="step",
        step=step.key,
        text=f"Step {position} of {total}: {step.title}",
        blocks=[context_block(f"<@{ctx.slack_user_id}> Step {position} of {total}"), *step.render(ctx)],
    )


def _summary_message(step: DmSetupStep, ts: str, *, skipped: bool) -> SlackDmSetupMessage:
    line = f"Skipped: {step.title}" if skipped else f":white_check_mark: {step.done_text}"
    return SlackDmSetupMessage(
        kind="step", step=step.key, text=line, blocks=[context_block(line)], ts=ts, summarizes_step=True
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
    return SlackDmSetupMessage(kind="ready", text="PostHog is ready", blocks=[section_block(text)])


def _status(progress: str, pending: list[DmSetupStep], skipped: list[DmSetupStep]) -> str:
    current = f"current step: {pending[0].key}" if pending else "ready"
    skips = ", ".join(step.key for step in skipped) or "none"
    return f"{progress} · {current} · skipped: {skips}"


def plan_dm_setup(integration: WorkspaceIntegration, slack_user_id: str) -> SlackDmSetupPlan:
    """Reads only, except that it stores that there is nothing to set up."""
    slack_workspace_id = integration.integration_id
    state = resolve_dm_setup_card(slack_workspace_id, slack_user_id)
    if state is not None and state.completed:
        return DM_SETUP_DONE_PLAN

    ctx = DmSetupContext(integration=integration, slack_user_id=slack_user_id)
    steps = [step for step in DM_SETUP_STEPS if step.applies(ctx)]
    done = [step for step in steps if step.is_done(ctx)]
    skipped_keys = state.skipped if state else ()
    skipped = [step for step in steps if step.skippable and step.key in skipped_keys and step not in done]
    pending = [step for step in steps if step not in done and step not in skipped]
    progress = f"{len(steps) - len(pending)} of {len(steps)} steps done"
    status = _status(progress, pending, skipped)

    if state is None or state.root_ts is None:
        if not pending:
            # Storing this saves a workflow run on each later open of the DM.
            update_dm_setup_card(slack_workspace_id, slack_user_id, completed=True)
            return DM_SETUP_DONE_PLAN
        return SlackDmSetupPlan(edits=[], post=_root_message(progress, ready=False), finished=False, status=status)

    edits = [
        _summary_message(step, state.step_ts[step.key], skipped=step in skipped)
        for step in [*done, *skipped]
        if step.key in state.step_ts and step.key not in state.summarized
    ]
    if not pending:
        edits.append(_root_message(progress, ready=True, ts=state.root_ts))
        return SlackDmSetupPlan(edits=edits, post=_ready_message(ctx, skipped), finished=True, status=status)

    if state.progress != progress:
        edits.append(_root_message(progress, ready=False, ts=state.root_ts))
    current = _step_message(ctx, pending[0], len(steps) - len(pending) + 1, len(steps))
    current_ts = state.step_ts.get(pending[0].key)
    if current_ts is None:
        return SlackDmSetupPlan(edits=edits, post=current, finished=False, status=status)
    # Rendering the shown step again keeps its content fresh, such as the 15-minute account link.
    edits.append(replace(current, ts=current_ts))
    return SlackDmSetupPlan(edits=edits, post=None, finished=False, status=status)


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
