"""Temporal workflows for suggested dashboards.

- Discovery runs every 5 minutes. It finds the teams whose metric names changed and starts one suggest
  workflow for each.
- Suggest analyzes one team: it updates the team's suggestions and starts a generate workflow for each
  group of metrics that the model wants a new dashboard for.
- Generate drafts a dashboard, then renders and checks a picture of it for up to MAX_ROUNDS rounds.
"""

from datetime import timedelta

import temporalio.common
import temporalio.workflow
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.metrics.backend.temporal.activities import (
        analyze_team_activity,
        check_preview_activity,
        draft_template_activity,
        find_teams_to_analyze_activity,
        finish_generation_activity,
        render_preview_activity,
        start_generation_activity,
    )
    from products.metrics.backend.temporal.inputs import (
        DISCOVERY_WORKFLOW_NAME,
        GENERATE_WORKFLOW_NAME,
        SUGGEST_WORKFLOW_NAME,
        DiscoveryInputs,
        FinishInputs,
        GenerateInputs,
        RoundInputs,
        SuggestInputs,
        generate_workflow_id,
        suggest_workflow_id,
    )

MAX_ROUNDS = 3
SUGGEST_TIMEOUT = timedelta(minutes=20)
GENERATE_TIMEOUT = timedelta(hours=1)
_SHORT = timedelta(minutes=2)
_ANALYZE = timedelta(minutes=10)
_MODEL_STEP = timedelta(minutes=10)
_RENDER = timedelta(minutes=5)
_HEARTBEAT = timedelta(minutes=2)
_RETRY = temporalio.common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10))
# A render fails while the web server restarts, so it waits longer between tries.
_RENDER_RETRY = temporalio.common.RetryPolicy(
    maximum_attempts=3, initial_interval=timedelta(seconds=20), backoff_coefficient=2
)


def _error_message(error: Exception) -> str:
    if isinstance(error, ActivityError) and error.cause is not None:
        return str(error.cause)[:500]
    return str(error)[:500]


@temporalio.workflow.defn(name=DISCOVERY_WORKFLOW_NAME)
class MetricsDashboardDiscoveryWorkflow(PostHogWorkflow):
    inputs_cls = DiscoveryInputs

    @temporalio.workflow.run
    async def run(self, inputs: DiscoveryInputs) -> int:
        team_ids = await temporalio.workflow.execute_activity(
            find_teams_to_analyze_activity,
            inputs,
            start_to_close_timeout=_ANALYZE,
            heartbeat_timeout=_HEARTBEAT,
            retry_policy=_RETRY,
        )
        started = 0
        for team_id in team_ids:
            try:
                # Abandoned, so that a slow team never holds up the next sweep.
                await temporalio.workflow.start_child_workflow(
                    MetricsDashboardSuggestWorkflow.run,
                    SuggestInputs(team_id=team_id),
                    id=suggest_workflow_id(team_id),
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    execution_timeout=SUGGEST_TIMEOUT,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                continue
        return started


@temporalio.workflow.defn(name=SUGGEST_WORKFLOW_NAME)
class MetricsDashboardSuggestWorkflow(PostHogWorkflow):
    inputs_cls = SuggestInputs

    @temporalio.workflow.run
    async def run(self, inputs: SuggestInputs) -> int:
        result = await temporalio.workflow.execute_activity(
            analyze_team_activity,
            inputs,
            start_to_close_timeout=_ANALYZE,
            heartbeat_timeout=_HEARTBEAT,
            retry_policy=_RETRY,
        )
        for request in result.generation_requests:
            try:
                await temporalio.workflow.start_child_workflow(
                    MetricsDashboardGenerateWorkflow.run,
                    GenerateInputs(team_id=inputs.team_id, request=request),
                    id=generate_workflow_id(request.key),
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    execution_timeout=GENERATE_TIMEOUT,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
            except WorkflowAlreadyStartedError:
                continue
        return result.suggestion_count


@temporalio.workflow.defn(name=GENERATE_WORKFLOW_NAME)
class MetricsDashboardGenerateWorkflow(PostHogWorkflow):
    inputs_cls = GenerateInputs

    @temporalio.workflow.run
    async def run(self, inputs: GenerateInputs) -> str | None:
        template_id = await temporalio.workflow.execute_activity(
            start_generation_activity, inputs, start_to_close_timeout=_SHORT, retry_policy=_RETRY
        )
        if template_id is None:
            return None
        error: str | None = None
        try:
            panel_count = await temporalio.workflow.execute_activity(
                draft_template_activity,
                template_id,
                start_to_close_timeout=_MODEL_STEP,
                heartbeat_timeout=_HEARTBEAT,
                retry_policy=_RETRY,
            )
            if panel_count:
                await self._check_rounds(template_id)
        except ActivityError as activity_error:
            error = _error_message(activity_error)
        await temporalio.workflow.execute_activity(
            finish_generation_activity,
            FinishInputs(template_id=template_id, error=error),
            start_to_close_timeout=_SHORT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )
        return template_id

    async def _check_rounds(self, template_id: str) -> None:
        """Render and check pictures. The last round only records a verdict, so its picture shows the final panels."""
        for round_number in range(1, MAX_ROUNDS + 1):
            try:
                asset_id = await temporalio.workflow.execute_activity(
                    render_preview_activity,
                    RoundInputs(template_id=template_id, round=round_number),
                    start_to_close_timeout=_RENDER,
                    heartbeat_timeout=_HEARTBEAT,
                    retry_policy=_RENDER_RETRY,
                )
            except ActivityError:
                # Without a picture there is nothing to check. The panels so far go to the review as they are.
                return
            if asset_id is None:
                return
            looks_good = await temporalio.workflow.execute_activity(
                check_preview_activity,
                RoundInputs(template_id=template_id, round=round_number, revise=round_number < MAX_ROUNDS),
                start_to_close_timeout=_MODEL_STEP,
                heartbeat_timeout=_HEARTBEAT,
                retry_policy=_RETRY,
            )
            if looks_good:
                return
