# Workflows in this module run on the max-ai temporal task queue.
import json
import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

from products.slack_app.backend.temporal import (
    POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE,
    PostHogCodeSlackMentionWorkflowInputs,
    SlackAppModelOverride,
    SlackAppModelOverrideInput,
    SlackAppModelRouterInput,
    SlackAppProjectRoute,
    SlackAppProjectRouteInput,
    cascade_posthog_code_repository_activity,
    classify_posthog_code_task_needs_repo_activity,
    classify_slack_app_model_override_activity,
    classify_slack_app_model_router_activity,
    classify_slack_app_project_route_activity,
    classify_untagged_followup_activity,
    classify_untagged_question_activity,
    collect_posthog_code_thread_messages_activity,
    create_posthog_code_task_for_repo_activity,
    discover_posthog_code_repository_via_agent_activity,
    enforce_posthog_code_billing_quota_activity,
    forward_posthog_code_followup_activity,
    post_posthog_code_internal_error_activity,
    post_posthog_code_picker_timeout_activity,
    post_posthog_code_repo_picker_activity,
    posthog_code_thread_has_task_activity,
    request_untagged_followup_confirmation_activity,
    request_untagged_question_confirmation_activity,
)

if TYPE_CHECKING:
    from products.slack_app.backend.services.slack_messages import SlackThreadMessage

POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS = 10 * 60
POSTHOG_CODE_SLACK_PICKER_TIMEOUT_MINUTES = 15


@workflow.defn(name="slack-app-mention-processing")
class SlackAppMentionProcessingWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._selected_repo: str | None = None
        self._repo_selection_resolved = False

    @workflow.signal
    async def repo_selected(self, repository: str) -> None:
        if not self._repo_selection_resolved:
            self._repo_selection_resolved = True
            self._selected_repo = repository

    @workflow.signal
    async def no_repo_needed(self) -> None:
        if not self._repo_selection_resolved:
            self._repo_selection_resolved = True
            self._selected_repo = None

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogCodeSlackMentionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return PostHogCodeSlackMentionWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostHogCodeSlackMentionWorkflowInputs) -> None:
        event = inputs.event
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        slack_user_id = event.get("user")

        if not channel or not thread_ts or not slack_user_id:
            return

        # An untagged question stays silent, error replies included, until its author's
        # mode lets the run answer. Old histories carry no such input, so they never skip.
        silent_on_error = inputs.untagged_question and not inputs.untagged_question_confirmed
        try:
            # Gate every workflow entry on the team's AI-credits quota before any
            # other activity runs. Webhook-level short-circuit catches the common
            # case (see products/slack_app/backend/api.py); this is the defense in
            # depth that also covers replays, manual workflow starts, and the race
            # where the webhook saw "not limited" but Redis flipped before we got
            # here.
            blocked = await _execute_posthog_code_activity(
                enforce_posthog_code_billing_quota_activity,
                inputs,
                channel,
                thread_ts,
                slack_user_id,
            )
            if blocked:
                return

            # Both gates run before anything visible, because nobody tagged us in this message.
            if silent_on_error:
                answerable = await _execute_posthog_code_activity(classify_untagged_question_activity, inputs)
                if not answerable:
                    return
                awaiting_confirmation = await _execute_posthog_code_activity(
                    request_untagged_question_confirmation_activity, inputs
                )
                if awaiting_confirmation:
                    return
                silent_on_error = False

            prework = await _prework_in_parallel(inputs, channel, thread_ts, slack_user_id)
            if prework is None:
                return
            inputs = prework.inputs
            model_override = prework.model_override
            thread_messages = prework.thread_messages
            user_id = inputs.user_id

            repository: str | None
            # Set only on the ambiguous path that runs the discovery sandbox
            repo_research_task_id: str | None = None
            repo_research_run_id: str | None = None

            cascade = await _execute_posthog_code_activity(
                cascade_posthog_code_repository_activity,
                inputs,
                event.get("text", ""),
                user_id,
                thread_messages,
                event.get("ts"),
            )

            if cascade.mode == "auto":
                repository = cascade.repository
            elif cascade.mode == "no_repo":
                # Cascade emits `no_repo` whenever the mentioning user resolves no repos.
                # The mention still becomes a task. Whether the ask needs code is the
                # agent's call once it can see the request, and the agent is the one that
                # tells the user to connect GitHub if it turns out to need a repo. Deciding
                # that here meant a single false positive from the needs-repo classifier
                # walled a plain analytics question behind a Connect button.
                repository = None
            else:
                # Multiple candidates and no explicit mention. Cheap Haiku
                # check first to skip the agent entirely for analytics/config
                # questions; otherwise hand off to the discovery agent.
                needs_repo = await _execute_posthog_code_activity(
                    classify_posthog_code_task_needs_repo_activity,
                    event.get("text", ""),
                    thread_messages,
                    inputs,
                )
                if not needs_repo:
                    repository = None
                else:
                    outcome = await _execute_posthog_code_agent_activity(
                        discover_posthog_code_repository_via_agent_activity,
                        inputs,
                        channel,
                        event,
                        thread_messages,
                        user_id,
                    )
                    repo_research_task_id = outcome.repo_research_task_id
                    repo_research_run_id = outcome.repo_research_run_id

                    if outcome.status == "found":
                        repository = outcome.repository
                    elif outcome.status == "no_match":
                        repository = None
                    else:
                        if outcome.usage_limited:
                            # The activity told the thread the team is out of credits. A picked repo would fail the same way.
                            return
                        # Agent crashed/timed out/hallucinated — italicize its reason
                        # above the picker guidance so the user sees why.
                        picker_guidance = f"_{outcome.reason}_\n\n{POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE}"
                        await _execute_posthog_code_activity(
                            post_posthog_code_repo_picker_activity,
                            inputs,
                            channel,
                            thread_ts,
                            slack_user_id,
                            event,
                            workflow.info().workflow_id,
                            picker_guidance,
                            True,
                            user_id,
                        )
                        try:
                            await workflow.wait_condition(
                                lambda: self._repo_selection_resolved,
                                timeout=timedelta(minutes=POSTHOG_CODE_SLACK_PICKER_TIMEOUT_MINUTES),
                            )
                        except TimeoutError:
                            await _execute_posthog_code_activity(
                                post_posthog_code_picker_timeout_activity, inputs, channel, thread_ts
                            )
                            return
                        repository = self._selected_repo

            # After repo selection, so the repository can inform the pick.
            model_override = await _execute_posthog_code_activity(
                classify_slack_app_model_router_activity,
                SlackAppModelRouterInput(
                    integration_id=inputs.integration_id,
                    slack_team_id=inputs.slack_team_id,
                    slack_user_id=slack_user_id,
                    user_id=user_id,
                    event_text=event.get("text", ""),
                    thread_ts=thread_ts,
                    repository=repository,
                    model_override=model_override,
                ),
            )

            await _execute_posthog_code_activity(
                create_posthog_code_task_for_repo_activity,
                inputs,
                channel,
                thread_ts,
                slack_user_id,
                user_id,
                event,
                thread_messages,
                repository,
                repo_research_task_id,
                repo_research_run_id,
                model_override,
            )
        except Exception as exc:
            workflow.logger.exception(
                "posthog_code_workflow_unhandled_exception",
                extra={
                    "channel": channel,
                    "thread_ts": thread_ts,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            if silent_on_error:
                return
            await _execute_posthog_code_activity(
                post_posthog_code_internal_error_activity,
                inputs,
                channel,
                thread_ts,
            )


@frozen
class _NewThreadPrework:
    """What the steps before repo selection hand to the rest of a new-thread run."""

    inputs: PostHogCodeSlackMentionWorkflowInputs
    model_override: SlackAppModelOverride | None
    thread_messages: "list[SlackThreadMessage]"


def _model_override_input(inputs: PostHogCodeSlackMentionWorkflowInputs, thread_ts: str) -> SlackAppModelOverrideInput:
    return SlackAppModelOverrideInput(
        integration_id=inputs.integration_id,
        slack_team_id=inputs.slack_team_id,
        event_text=inputs.event.get("text", ""),
        thread_ts=thread_ts,
    )


def _project_route_input(
    inputs: PostHogCodeSlackMentionWorkflowInputs, thread_ts: str, slack_user_id: str
) -> SlackAppProjectRouteInput:
    return SlackAppProjectRouteInput(
        integration_id=inputs.integration_id,
        slack_team_id=inputs.slack_team_id,
        event_text=inputs.event.get("text", ""),
        user_id=inputs.user_id,
        slack_user_id=slack_user_id,
        thread_ts=thread_ts,
    )


def _is_file_only_followup(event: dict[str, Any]) -> bool:
    event_files = event.get("files")
    event_has_files = isinstance(event_files, list) and len(event_files) > 0
    return event_has_files and not (event.get("text") or "").strip()


async def _untagged_followup_is_agent_directed(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str, slack_user_id: str
) -> bool:
    return await _execute_posthog_code_activity(
        classify_untagged_followup_activity,
        inputs,
        channel,
        thread_ts,
        slack_user_id,
        inputs.event.get("text", ""),
    )


async def _awaiting_followup_confirmation(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str, slack_user_id: str
) -> bool:
    return await _execute_posthog_code_activity(
        request_untagged_followup_confirmation_activity,
        inputs,
        channel,
        thread_ts,
        slack_user_id,
    )


async def _collect_thread_messages(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str
) -> "list[SlackThreadMessage]":
    # A forked run is the one case where the thread we read and the thread we
    # answer in are different. `channel`/`thread_ts` stay the DM throughout —
    # they own the task, the mapping, the reaction and every follow-up — while
    # the context block is built from the channel thread the user forked.
    # Unset for every other run, so both pairs coincide.
    return await _execute_posthog_code_activity(
        collect_posthog_code_thread_messages_activity,
        inputs,
        inputs.fork_source_channel or channel,
        inputs.fork_source_thread_ts or thread_ts,
    )


async def _forward_followup(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    model_override: SlackAppModelOverride | None,
) -> bool:
    return await _execute_posthog_code_activity(
        forward_posthog_code_followup_activity,
        inputs,
        channel,
        thread_ts,
        slack_user_id,
        inputs.event.get("text", ""),
        inputs.event.get("ts"),
        model_override,
    )


async def _apply_project_route(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    project_route: SlackAppProjectRoute | None,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
) -> PostHogCodeSlackMentionWorkflowInputs | None:
    """The inputs to continue with, or ``None`` when the routed project is over its quota."""
    if project_route is None:
        return inputs
    inputs = replace(inputs, integration_id=project_route.integration_id)
    # The gate at the top of the run checked the project routing had
    # resolved, not the one the message named. Without this the run spends
    # the needs-repo classifier and possibly a discovery sandbox before task
    # creation refuses on the same quota.
    blocked = await _execute_posthog_code_activity(
        enforce_posthog_code_billing_quota_activity,
        inputs,
        channel,
        thread_ts,
        slack_user_id,
    )
    return None if blocked else inputs


async def _prework_in_parallel(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str, slack_user_id: str
) -> _NewThreadPrework | None:
    """The steps before repo selection, with the independent steps run together.

    Each step reads only the message and the resolved project, so the slowest step sets
    the wall time instead of the sum of all of them.
    """
    # Read a model or effort request ("use fable for this one", "actually run
    # this on opus") out of the message. One call serves whichever path the
    # message takes, and recording the choice in history once stops a retry of
    # either activity from landing on a different model than the first attempt announced.
    model_override_task = asyncio.create_task(
        _execute_posthog_code_activity(
            classify_slack_app_model_override_activity, _model_override_input(inputs, thread_ts)
        )
    )

    if inputs.untagged_followup:
        # Untagged replies never open a thread. The override is wasted on a dropped reply.
        unconfirmed_followup = not inputs.untagged_followup_confirmed
        # Untagged thread replies face the Haiku classifier before any forward.
        # Drop on chitchat or any failure (default-deny). File-only replies skip
        # the classifier: there is no text to classify, and default-deny would
        # silently drop the attachment.
        if unconfirmed_followup and not _is_file_only_followup(inputs.event):
            if not await _untagged_followup_is_agent_directed(inputs, channel, thread_ts, slack_user_id):
                return None
        # A confirmed run skips the prompt, because the answer is what re-dispatched this.
        if unconfirmed_followup and await _awaiting_followup_confirmation(inputs, channel, thread_ts, slack_user_id):
            return None
        await _forward_followup(inputs, channel, thread_ts, slack_user_id, await model_override_task)
        return None

    if await _execute_posthog_code_activity(posthog_code_thread_has_task_activity, inputs, channel, thread_ts):
        if await _forward_followup(inputs, channel, thread_ts, slack_user_id, await model_override_task):
            return None

    # A routed project is an install in the same Slack workspace, so the bot reads the same thread.
    project_route, thread_messages, model_override = await asyncio.gather(
        _execute_posthog_code_activity(
            classify_slack_app_project_route_activity, _project_route_input(inputs, thread_ts, slack_user_id)
        ),
        _collect_thread_messages(inputs, channel, thread_ts),
        model_override_task,
    )
    routed_inputs = await _apply_project_route(inputs, project_route, channel, thread_ts, slack_user_id)
    if routed_inputs is None or not thread_messages:
        return None
    return _NewThreadPrework(inputs=routed_inputs, model_override=model_override, thread_messages=thread_messages)


async def _execute_posthog_code_activity(activity_fn: Any, *args: Any) -> Any:
    return await workflow.execute_activity(
        activity_fn,
        args=args,
        start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )


async def _execute_posthog_code_agent_activity(activity_fn: Any, *args: Any) -> Any:
    """Wrapper for the discovery-agent activity.

    No retries: a hung agent shouldn't block the Slack thread for tens of
    minutes — the activity catches its own exceptions and returns
    `status='failed'` so the workflow falls through to the picker.
    """
    return await workflow.execute_activity(
        activity_fn,
        args=args,
        start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS),
        heartbeat_timeout=timedelta(minutes=5),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
