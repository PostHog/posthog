"""Only the per-person workflow calls these, through activities, so renders for one person never overlap."""

from dataclasses import replace
from typing import Literal

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStep
from products.slack_app.backend.logic.onboarding.steps import ONBOARDING_STEPS, STEPS_BY_KEY
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
    return f"{finished} of {len(checked)} {'step' if len(checked) == 1 else 'steps'} done"


_CHECKLIST_LINES: dict[StepStatus, str] = {
    "done": ":white_check_mark: {done_text}",
    "already_set": ":white_check_mark: {title}: already set",
    "not_needed": ":heavy_minus_sign: {title}: not needed",
    "skipped": ":heavy_minus_sign: {title}: skipped",
    "pending": ":white_small_square: {title}",
}


def _checklist(checked: list[_PlannedStep]) -> str:
    current = _current(checked)
    lines = []
    for item in checked:
        if item is current:
            line = f":arrow_right: *{item.step.title}*"
        else:
            line = _CHECKLIST_LINES[item.status].format(title=item.step.title, done_text=item.step.done_text)
        lines.append(f"{item.number}. {line}")
    return "\n".join(lines)


def _root_status(checked: list[_PlannedStep]) -> str:
    """Stored so the thread can tell when any checklist line changes, even when the count stays the same."""
    return f"{_progress(checked)}\n{_checklist(checked)}"


def _root_message(checked: list[_PlannedStep], *, ready: bool, ts: str | None = None) -> SlackAppOnboardingMessage:
    return SlackAppOnboardingMessage(
        kind="root",
        text="PostHog is set up" if ready else "Set up PostHog in Slack",
        blocks=[
            section_block(ONBOARDING_INTRO_TEXT),
            context_block(":white_check_mark: Setup done" if ready else _progress(checked)),
            context_block(_checklist(checked)),
        ],
        ts=ts,
        root_status=_root_status(checked),
    )


def _passed_notes(checked: list[_PlannedStep], current: _PlannedStep) -> list[str]:
    """The steps that were set elsewhere after the previous reply, so the thread jumps over them."""
    notes = []
    for item in reversed(checked[: current.number - 1]):
        if item.shown:
            break
        reason = "is already set" if item.status == "already_set" else "is not needed anymore"
        notes.append(f"Step {item.number}, {item.step.title}, {reason}, so I skipped it.")
    return list(reversed(notes))


def _step_message(
    ctx: OnboardingContext, checked: list[_PlannedStep], current: _PlannedStep
) -> SlackAppOnboardingMessage:
    position = f"Step {current.number} of {len(checked)}"
    # The mention makes the person follow the thread, so each new step reply notifies them.
    return SlackAppOnboardingMessage(
        kind="step",
        step=current.step.key,
        text=f"{position}: {current.step.title}",
        blocks=[
            context_block(f"<@{ctx.slack_user_id}> {position}"),
            *(context_block(note) for note in _passed_notes(checked, current)),
            *current.step.render(ctx),
        ],
    )


_SUMMARY_LINES: dict[StepStatus, str] = {
    "done": ":white_check_mark: {done_text}",
    "not_needed": "Not needed: {title}",
    "skipped": "Skipped: {title}",
}


def _summary_message(item: _PlannedStep, ts: str) -> SlackAppOnboardingMessage:
    line = _SUMMARY_LINES[item.status].format(title=item.step.title, done_text=item.step.done_text)
    return SlackAppOnboardingMessage(
        kind="step", step=item.step.key, text=line, blocks=[context_block(line)], ts=ts, summarizes_step=True
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
    """Reads only, except that it stores that there is nothing to set up."""
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is not None and state.completed:
        return ONBOARDING_DONE_PLAN

    ctx = OnboardingContext(integration=integration, slack_user_id=slack_user_id)
    if state is None or state.root_ts is None:
        # The thread promises these steps at its start.
        steps = [step for step in ONBOARDING_STEPS if step.applies(ctx) and not step.is_done(ctx)]
        if not steps:
            # Storing this saves a workflow run on each later open of the DM.
            update_onboarding(slack_workspace_id, slack_user_id, completed_reason="nothing_to_set_up")
            return ONBOARDING_DONE_PLAN
        checked = [
            _PlannedStep(number=number, step=step, status="pending", shown=False)
            for number, step in enumerate(steps, start=1)
        ]
        root = replace(_root_message(checked, ready=False), planned=[step.key for step in steps])
        return SlackAppOnboardingPlan(edits=[], post=root, finished=False, status=_status(checked))

    checked = _check_planned(ctx, state.planned, state.step_ts, state.skipped)
    status = _status(checked)
    edits = [
        _summary_message(item, state.step_ts[item.step.key])
        for item in checked
        if item.shown and item.status != "pending" and item.step.key not in state.summarized
    ]
    current = _current(checked)
    if current is None:
        edits.append(_root_message(checked, ready=True, ts=state.root_ts))
        return SlackAppOnboardingPlan(edits=edits, post=_ready_message(ctx, checked), finished=True, status=status)

    if state.root_status != _root_status(checked):
        edits.append(_root_message(checked, ready=False, ts=state.root_ts))
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
    if message.kind == "root" and message.root_status:
        update_onboarding(slack_workspace_id, slack_user_id, root_status=message.root_status)
    if message.summarizes_step and message.step:
        update_onboarding(slack_workspace_id, slack_user_id, summarized_step=message.step)
