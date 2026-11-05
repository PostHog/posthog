"""Only the per-person workflow calls these, through activities, so renders for one person never overlap."""

from dataclasses import replace

from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStepSpec
from products.slack_app.backend.logic.onboarding.steps import ONBOARDING_STEPS
from products.slack_app.backend.services.slack_messages import context_block, section_block
from products.slack_app.backend.services.slack_settings import resolve_onboarding, update_onboarding
from products.slack_app.backend.services.slack_welcome_messages import ONBOARDING_INTRO_TEXT, build_onboarding_ready
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration
from products.slack_app.backend.temporal.types import (
    ONBOARDING_DONE_PLAN,
    SlackAppOnboardingMessage,
    SlackAppOnboardingPlan,
)

# pinned: analytics event names, renaming breaks dashboards
SETUP_STARTED_EVENT = "slack app onboarding started"
STEP_SHOWN_EVENT = "slack app onboarding step shown"
SETUP_COMPLETED_EVENT = "slack app onboarding completed"


def _root_message(progress: str, *, ready: bool, ts: str | None = None) -> SlackAppOnboardingMessage:
    return SlackAppOnboardingMessage(
        kind="root",
        text="PostHog is set up" if ready else "Set up PostHog in Slack",
        blocks=[
            section_block(ONBOARDING_INTRO_TEXT),
            context_block(":white_check_mark: Setup done" if ready else progress),
        ],
        ts=ts,
        progress=progress,
    )


def _step_message(ctx: OnboardingContext, step: OnboardingStepSpec, position: int) -> SlackAppOnboardingMessage:
    # The mention makes the person follow the thread, so each new step reply notifies them.
    return SlackAppOnboardingMessage(
        kind="step",
        step=step.key,
        text=f"Step {position}: {step.title}",
        blocks=[context_block(f"<@{ctx.slack_user_id}> Step {position}"), *step.render(ctx)],
    )


def _progress(finished: int) -> str:
    if finished == 0:
        return "No steps done yet"
    return "1 step done" if finished == 1 else f"{finished} steps done"


def _summary_message(step: OnboardingStepSpec, ts: str, *, skipped: bool) -> SlackAppOnboardingMessage:
    line = f"Skipped: {step.title}" if skipped else f":white_check_mark: {step.done_text}"
    return SlackAppOnboardingMessage(
        kind="step", step=step.key, text=line, blocks=[context_block(line)], ts=ts, summarizes_step=True
    )


def _ready_message(ctx: OnboardingContext, skipped: list[OnboardingStepSpec]) -> SlackAppOnboardingMessage:
    text, blocks = build_onboarding_ready(ctx.integration, ctx.slack_user_id, [step.title for step in skipped])
    return SlackAppOnboardingMessage(kind="ready", text=text, blocks=blocks)


def _status(progress: str, pending: list[OnboardingStepSpec], skipped: list[OnboardingStepSpec]) -> str:
    current = f"current step: {pending[0].key}" if pending else "ready"
    skips = ", ".join(step.key for step in skipped) or "none"
    return f"{progress} · {current} · skipped: {skips}"


def plan_onboarding(integration: WorkspaceIntegration, slack_user_id: str) -> SlackAppOnboardingPlan:
    """Reads only, except that it stores that there is nothing to set up."""
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is not None and state.completed:
        return ONBOARDING_DONE_PLAN

    ctx = OnboardingContext(integration=integration, slack_user_id=slack_user_id)
    steps = [step for step in ONBOARDING_STEPS if step.applies(ctx)]
    done = [step for step in steps if step.is_done(ctx)]
    skipped_keys = state.skipped if state else ()
    skipped = [step for step in steps if step.skippable and step.key in skipped_keys and step not in done]
    pending = [step for step in steps if step not in done and step not in skipped]
    # Count only steps in this thread. A step done before it came up never shows, and the total has no
    # fixed value, because the steps for admins apply only once the account link says who the person is.
    step_ts = state.step_ts if state else {}
    finished_in_thread = [step for step in steps if step.key in step_ts and step not in pending]
    progress = _progress(len(finished_in_thread))
    status = _status(progress, pending, skipped)

    if state is None or state.root_ts is None:
        if not pending:
            # Storing this saves a workflow run on each later open of the DM.
            update_onboarding(slack_workspace_id, slack_user_id, completed_reason="nothing_to_set_up")
            return ONBOARDING_DONE_PLAN
        return SlackAppOnboardingPlan(
            edits=[], post=_root_message(progress, ready=False), finished=False, status=status
        )

    edits = [
        _summary_message(step, state.step_ts[step.key], skipped=step in skipped)
        for step in [*done, *skipped]
        if step.key in state.step_ts and step.key not in state.summarized
    ]
    if not pending:
        edits.append(_root_message(progress, ready=True, ts=state.root_ts))
        return SlackAppOnboardingPlan(edits=edits, post=_ready_message(ctx, skipped), finished=True, status=status)

    if state.progress != progress:
        edits.append(_root_message(progress, ready=False, ts=state.root_ts))
    current = _step_message(ctx, pending[0], len(finished_in_thread) + 1)
    current_ts = state.step_ts.get(pending[0].key)
    if current_ts is None:
        return SlackAppOnboardingPlan(edits=edits, post=current, finished=False, status=status)
    # Rendering the shown step again keeps its content fresh, such as the 15-minute account link.
    edits.append(replace(current, ts=current_ts))
    return SlackAppOnboardingPlan(edits=edits, post=None, finished=False, status=status)


def post_onboarding_message(
    integration: WorkspaceIntegration, slack_user_id: str, message: SlackAppOnboardingMessage
) -> None:
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    client = SlackIntegration(integration).client
    if message.kind == "root":
        response = client.chat_postMessage(channel=slack_user_id, text=message.text, blocks=message.blocks)
        update_onboarding(
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
        update_onboarding(slack_workspace_id, slack_user_id, step_ts=(message.step, str(response["ts"])))
        capture_slack_event(integration, STEP_SHOWN_EVENT, slack_user_id=slack_user_id, step=message.step)
    elif message.kind == "ready":
        update_onboarding(slack_workspace_id, slack_user_id, completed_reason="finished")
        capture_slack_event(
            integration, SETUP_COMPLETED_EVENT, slack_user_id=slack_user_id, skipped_steps=list(state.skipped)
        )


def edit_onboarding_message(
    integration: WorkspaceIntegration, slack_user_id: str, message: SlackAppOnboardingMessage
) -> None:
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is None or state.channel is None or message.ts is None:
        return
    SlackIntegration(integration).client.chat_update(
        channel=state.channel, ts=message.ts, text=message.text, blocks=message.blocks
    )
    if message.kind == "root" and message.progress:
        update_onboarding(slack_workspace_id, slack_user_id, progress=message.progress)
    if message.summarizes_step and message.step:
        update_onboarding(slack_workspace_id, slack_user_id, summarized_step=message.step)
