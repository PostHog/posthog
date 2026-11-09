"""Only the per-person workflow calls these, through activities, so renders for one person never overlap."""

from dataclasses import replace
from typing import Literal

from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.onboarding.dispatch import request_onboarding
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStep
from products.slack_app.backend.logic.onboarding.steps import ONBOARDING_STEPS, STEPS_BY_KEY
from products.slack_app.backend.services.slack_messages import context_block, section_block
from products.slack_app.backend.services.slack_settings import resolve_onboarding, update_onboarding
from products.slack_app.backend.services.slack_welcome_messages import (
    build_onboarding_ready,
    onboarding_done_text,
    onboarding_intro_text,
)
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
REMINDED_EVENT = "slack app onboarding reminded"


StepStatus = Literal["done", "already_set", "not_needed", "skipped", "pending"]


@frozen
class _PlannedStep:
    number: int
    step: OnboardingStep
    status: StepStatus
    # Whether the step has a reply in the thread.
    shown: bool


def _check_planned(
    ctx: OnboardingContext, planned: tuple[str, ...], step_ts: dict[str, str], skipped: tuple[str, ...]
) -> list[_PlannedStep]:
    steps = [STEPS_BY_KEY[key] for key in planned if key in STEPS_BY_KEY]
    checked = []
    for number, step in enumerate(steps, start=1):
        shown = step.key in step_ts
        status: StepStatus
        if not step.applies(ctx):
            status = "not_needed"
        elif step.is_done(ctx):
            status = "done" if shown else "already_set"
        elif step.skippable and step.key in skipped:
            status = "skipped"
        else:
            status = "pending"
        checked.append(_PlannedStep(number=number, step=step, status=status, shown=shown))
    return checked


def _current(checked: list[_PlannedStep]) -> _PlannedStep | None:
    return next((item for item in checked if item.status == "pending"), None)


def _progress(checked: list[_PlannedStep]) -> str:
    finished = sum(1 for item in checked if item.status != "pending")
    return f"{finished}/{len(checked)} done"


def _progress_bar(checked: list[_PlannedStep]) -> str:
    finished = sum(1 for item in checked if item.status != "pending")
    return f"{'▰' * finished}{'▱' * (len(checked) - finished)}  {_progress(checked)}"


def _root_message(
    ctx: OnboardingContext, checked: list[_PlannedStep], *, ready: bool, ts: str | None = None
) -> SlackAppOnboardingMessage:
    blocks = (
        [section_block(onboarding_done_text(ctx.slack_user_id))]
        if ready
        else [section_block(onboarding_intro_text(ctx.slack_user_id)), context_block(_progress_bar(checked))]
    )
    return SlackAppOnboardingMessage(
        kind="root",
        text="PostHog is set up" if ready else "Set up PostHog in Slack",
        blocks=blocks,
        ts=ts,
        root_status=_progress(checked),
    )


_SUMMARY_LINES: dict[StepStatus, str] = {
    "done": ":white_check_mark: {done_text}",
    "already_set": ":white_check_mark: {title}: already set",
    "not_needed": "Not needed: {title}",
    "skipped": "Skipped: {title}",
}


def _summary_line(item: _PlannedStep) -> str:
    return _SUMMARY_LINES[item.status].format(title=item.step.title, done_text=item.step.done_text)


def _passed(items: list[_PlannedStep]) -> list[_PlannedStep]:
    """The steps the thread jumped over at the start of ``items``, because they were set elsewhere."""
    passed = []
    for item in items:
        if item.shown or item.status == "pending":
            break
        passed.append(item)
    return passed


def _step_message(
    ctx: OnboardingContext, checked: list[_PlannedStep], current: _PlannedStep
) -> SlackAppOnboardingMessage:
    position = f"Step {current.number}/{len(checked)}"
    # A step jumped over before any reply has no summary to sit in, so it shows here.
    leading = [] if any(item.shown for item in checked[: current.number - 1]) else _passed(checked)
    # The mention makes the person follow the thread, so each new step reply notifies them.
    return SlackAppOnboardingMessage(
        kind="step",
        step=current.step.key,
        text=f"{position}: {current.step.title}",
        blocks=[
            *(context_block(_summary_line(item)) for item in leading),
            context_block(f"<@{ctx.slack_user_id}> {position}"),
            *current.step.render(ctx),
        ],
    )


def _summary_message(checked: list[_PlannedStep], item: _PlannedStep, ts: str) -> SlackAppOnboardingMessage:
    # The steps jumped over after this reply get their line here, so every step shows in the thread.
    lines = [_summary_line(later) for later in [item, *_passed(checked[item.number :])]]
    return SlackAppOnboardingMessage(
        kind="step",
        step=item.step.key,
        text="\n".join(lines),
        blocks=[context_block(line) for line in lines],
        ts=ts,
        summarizes_step=True,
    )


def _ready_message(ctx: OnboardingContext, checked: list[_PlannedStep]) -> SlackAppOnboardingMessage:
    skipped = [item.step.title for item in checked if item.status == "skipped"]
    text, blocks = build_onboarding_ready(ctx.integration, ctx.slack_user_id, skipped)
    return SlackAppOnboardingMessage(kind="ready", text=text, blocks=blocks)


def _status(checked: list[_PlannedStep]) -> str:
    current = _current(checked)
    skips = ", ".join(item.step.key for item in checked if item.status == "skipped") or "none"
    return f"{_progress(checked)} · {f'current step: {current.step.key}' if current else 'ready'} · skipped: {skips}"


def plan_onboarding(integration: WorkspaceIntegration, slack_user_id: str) -> SlackAppOnboardingPlan:
    """Reads only, except that it stores steps that join the thread and that there is nothing to set up."""
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is not None and state.completed:
        return ONBOARDING_DONE_PLAN

    ctx = OnboardingContext(integration=integration, slack_user_id=slack_user_id)
    skipped = state.skipped if state else ()
    if state is None or state.root_ts is None:
        # The thread promises these steps at its start.
        steps = [
            step for step in ONBOARDING_STEPS if step.key not in skipped and step.applies(ctx) and not step.is_done(ctx)
        ]
        if not steps:
            # Storing this saves a workflow run on each later open of the DM.
            update_onboarding(slack_workspace_id, slack_user_id, completed_reason="nothing_to_set_up")
            return ONBOARDING_DONE_PLAN
        checked = [
            _PlannedStep(number=number, step=step, status="pending", shown=False)
            for number, step in enumerate(steps, start=1)
        ]
        root = replace(_root_message(ctx, checked, ready=False), planned=[step.key for step in steps])
        return SlackAppOnboardingPlan(edits=[], post=root, finished=False, status=_status(checked))

    # A step can apply only after the account link, such as AI consent for an org admin. It joins at the end,
    # so the replies already in the thread keep their numbers.
    joining = [
        step.key
        for step in ONBOARDING_STEPS
        if step.key not in state.planned and step.key not in skipped and step.applies(ctx) and not step.is_done(ctx)
    ]
    planned = (*state.planned, *joining)
    if joining:
        update_onboarding(slack_workspace_id, slack_user_id, planned=list(planned))
    checked = _check_planned(ctx, planned, state.step_ts, skipped)
    status = _status(checked)
    edits = [
        _summary_message(checked, item, state.step_ts[item.step.key])
        for item in checked
        if item.shown and item.status != "pending" and item.step.key not in state.summarized
    ]
    current = _current(checked)
    if current is None:
        edits.append(_root_message(ctx, checked, ready=True, ts=state.root_ts))
        return SlackAppOnboardingPlan(edits=edits, post=_ready_message(ctx, checked), finished=True, status=status)

    if state.root_status != _progress(checked):
        edits.append(_root_message(ctx, checked, ready=False, ts=state.root_ts))
    message = _step_message(ctx, checked, current)
    current_ts = state.step_ts.get(current.step.key)
    if current_ts is None:
        return SlackAppOnboardingPlan(edits=edits, post=message, finished=False, status=status)
    # Rendering the shown step again keeps its content fresh, such as the 15-minute account link.
    edits.append(replace(message, ts=current_ts))
    return SlackAppOnboardingPlan(edits=edits, post=None, finished=False, status=status)


def post_onboarding_message(
    integration: WorkspaceIntegration, slack_user_id: str, message: SlackAppOnboardingMessage
) -> None:
    slack_workspace_id = integration.integration_id
    client = SlackIntegration(integration).client
    if message.kind == "root":
        response = client.chat_postMessage(channel=slack_user_id, text=message.text, blocks=message.blocks)
        update_onboarding(
            slack_workspace_id,
            slack_user_id,
            root=(str(response["channel"]), str(response["ts"])),
            planned=message.planned,
            root_status=message.root_status,
        )
        capture_slack_event(integration, SETUP_STARTED_EVENT, slack_user_id=slack_user_id)
        return

    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is None or state.channel is None or state.root_ts is None:
        # The top message was deleted earlier in this refresh. The next plan starts a new thread.
        return
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


def _forget_deleted_message(
    integration: WorkspaceIntegration, slack_user_id: str, message: SlackAppOnboardingMessage
) -> None:
    """Slack retention or an admin can delete a message. The thread then posts it again, or starts over
    when the top message is gone, instead of failing on each refresh."""
    slack_workspace_id = integration.integration_id
    if message.kind == "root":
        update_onboarding(slack_workspace_id, slack_user_id, reset_thread=True)
    elif message.summarizes_step and message.step:
        update_onboarding(slack_workspace_id, slack_user_id, summarized_step=message.step)
    elif message.step:
        update_onboarding(slack_workspace_id, slack_user_id, forget_step=message.step)
    # The rest of this refresh was planned for the old messages, so plan again.
    request_onboarding(integration, slack_user_id, may_start=False)


def remind_onboarding(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    """Posts at most one reminder per person, as a reply that mentions them, so Slack notifies them."""
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is None or state.completed or state.reminded_at or state.channel is None or state.root_ts is None:
        return
    ctx = OnboardingContext(integration=integration, slack_user_id=slack_user_id)
    checked = _check_planned(ctx, state.planned, state.step_ts, state.skipped)
    current = _current(checked)
    if current is None or not current.shown:
        return
    text = (
        f"<@{slack_user_id}> Your PostHog setup is waiting at step {current.number} of {len(checked)}, "
        f"{current.step.title}. Pick it up above when you have a minute, or skip the steps you don't need."
    )
    SlackIntegration(integration).client.chat_postMessage(
        channel=state.channel, thread_ts=state.root_ts, text=text, blocks=[section_block(text)]
    )
    update_onboarding(slack_workspace_id, slack_user_id, reminded=True)
    capture_slack_event(integration, REMINDED_EVENT, slack_user_id=slack_user_id, step=current.step.key)


def edit_onboarding_message(
    integration: WorkspaceIntegration, slack_user_id: str, message: SlackAppOnboardingMessage
) -> None:
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is None or state.channel is None or message.ts is None:
        return
    try:
        SlackIntegration(integration).client.chat_update(
            channel=state.channel, ts=message.ts, text=message.text, blocks=message.blocks
        )
    except SlackApiError as error:
        if error.response.get("error") != "message_not_found":
            raise
        _forget_deleted_message(integration, slack_user_id, message)
        return
    if message.kind == "root" and message.root_status:
        update_onboarding(slack_workspace_id, slack_user_id, root_status=message.root_status)
    if message.summarizes_step and message.step:
        update_onboarding(slack_workspace_id, slack_user_id, summarized_step=message.step)
