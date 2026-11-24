"""Compute MCP Wrapped for chosen projects, or every project with tool calls this year, a few at a time.

Nothing schedules this workflow. Someone starts it when the year's wrap should be filled:

    python manage.py run_mcp_analytics_wrapped --year <year> [--team-id <team_id> ...]

One project's failure is recorded and the run moves on, so a slow or broken project never blocks the rest.
"""

import asyncio
import dataclasses
from collections import Counter
from typing import Any

import temporalio
import temporalio.workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.mcp_analytics.backend.temporal.wrapped.activities import (
        WrappedDiscoveryInputs,
        WrappedTeamInputs,
        discover_wrapped_team_ids_activity,
        generate_wrapped_activity,
    )
    from products.mcp_analytics.backend.temporal.wrapped.constants import (
        COORDINATOR_WORKFLOW_NAME,
        DISCOVERY_ACTIVITY_TIMEOUT,
        DISCOVERY_RETRY_POLICY,
        GENERATE_ACTIVITY_TIMEOUT,
        GENERATE_HEARTBEAT_TIMEOUT,
        GENERATE_RETRY_POLICY,
        MAX_CONCURRENT_TEAMS,
        TEAMS_PER_RUN,
    )


@dataclasses.dataclass(frozen=True)
class WrappedCoordinatorInputs:
    # None covers the year the run starts in.
    year: int | None = None
    # None discovers every project with tool calls in the year.
    team_ids: list[int] | None = None
    max_concurrent_teams: int = MAX_CONCURRENT_TEAMS
    teams_per_run: int = TEAMS_PER_RUN
    # Carried into the next run when this one continues as new, so the final result covers every project.
    statuses: dict[str, int] = dataclasses.field(default_factory=dict)
    failed_team_ids: list[int] = dataclasses.field(default_factory=list)


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class MCPWrappedCoordinatorWorkflow(PostHogWorkflow):
    @temporalio.workflow.run
    async def run(self, inputs: WrappedCoordinatorInputs) -> dict[str, Any]:
        if inputs.max_concurrent_teams < 1 or inputs.teams_per_run < 1:
            raise ApplicationError("max_concurrent_teams and teams_per_run must be at least 1", non_retryable=True)

        year = inputs.year or temporalio.workflow.now().year
        team_ids = inputs.team_ids
        if team_ids is None:
            team_ids = await temporalio.workflow.execute_activity(
                discover_wrapped_team_ids_activity,
                WrappedDiscoveryInputs(year=year),
                start_to_close_timeout=DISCOVERY_ACTIVITY_TIMEOUT,
                retry_policy=DISCOVERY_RETRY_POLICY,
            )

        # A repeated id would run twice in one batch, with both attempts writing the same row.
        team_ids = list(dict.fromkeys(team_ids))
        statuses: Counter[str] = Counter(inputs.statuses)
        failed_team_ids = list(inputs.failed_team_ids)
        this_run, remaining = team_ids[: inputs.teams_per_run], team_ids[inputs.teams_per_run :]
        for start in range(0, len(this_run), inputs.max_concurrent_teams):
            batch = this_run[start : start + inputs.max_concurrent_teams]
            results = await asyncio.gather(
                *(
                    temporalio.workflow.execute_activity(
                        generate_wrapped_activity,
                        WrappedTeamInputs(team_id=team_id, year=year),
                        start_to_close_timeout=GENERATE_ACTIVITY_TIMEOUT,
                        heartbeat_timeout=GENERATE_HEARTBEAT_TIMEOUT,
                        retry_policy=GENERATE_RETRY_POLICY,
                    )
                    for team_id in batch
                ),
                return_exceptions=True,
            )
            for team_id, result in zip(batch, results):
                if isinstance(result, BaseException):
                    temporalio.workflow.logger.warning("mcpa.wrapped.team_failed", extra={"team_id": team_id})
                    failed_team_ids.append(team_id)
                else:
                    statuses[result] += 1

        if remaining:
            temporalio.workflow.continue_as_new(
                dataclasses.replace(
                    inputs,
                    year=year,
                    team_ids=remaining,
                    statuses=dict(statuses),
                    failed_team_ids=failed_team_ids,
                )
            )

        return {
            "year": year,
            "teams": sum(statuses.values()) + len(failed_team_ids),
            "statuses": dict(statuses),
            "failed_team_ids": failed_team_ids,
        }
