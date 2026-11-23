import uuid
import logging
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.exceptions import (
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.rules import compile_filter_bytecode
from products.error_tracking.backend.models import ErrorTrackingIssueTagRule
from products.error_tracking.backend.temporal.tag_rule_sweep.activities import (
    INVALID_RULE_ERROR_TYPE,
    QUERY_LIMIT_ERROR_TYPE,
    sweep_team_tag_rules_activity,
)
from products.error_tracking.backend.temporal.tag_rule_sweep.types import (
    SweepTeamTagRulesInputs,
    SweepTeamTagRulesResult,
    TagRuleSweepInputs,
)
from products.error_tracking.backend.temporal.tag_rule_sweep.workflow import (
    FAILED_TEAMS_ERROR_TYPE,
    SWEEP_WINDOW,
    ErrorTrackingTagRuleSweepWorkflow,
)

QUERY = "products.error_tracking.backend.logic.issue_tags.sweep.execute_hogql_query"


@patch.object(team_flags, "feature_enabled_or_false", new=lambda *args, **kwargs: True)
class TestSweepTeamTagRulesActivity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        filters = {
            "type": "AND",
            "values": [{"type": "AND", "values": [{"key": "$pathname", "type": "event", "value": "/checkout"}]}],
        }
        ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team,
            label="Checkout",
            filters=filters,
            bytecode=compile_filter_bytecode(self.team.id, filters),
            order_key=1,
        )
        end = timezone.now()
        self.inputs = SweepTeamTagRulesInputs(team_id=self.team.id, start=end - SWEEP_WINDOW, end=end, dry_run=False)

    @parameterized.expand(
        [
            ("query_timeout", ClickHouseQueryTimeOut),
            ("query_memory_limit", ClickHouseQueryMemoryLimitExceeded),
            ("estimated_time_too_long", ClickHouseEstimatedQueryExecutionTimeTooLong),
        ]
    )
    def test_a_limit_of_the_query_stops_the_retries(self, _name: str, error_class: type[Exception]) -> None:
        with patch(QUERY, side_effect=error_class()), pytest.raises(ApplicationError) as failure:
            sweep_team_tag_rules_activity(self.inputs)

        assert (failure.value.type, failure.value.non_retryable) == (QUERY_LIMIT_ERROR_TYPE, True)

    def test_a_rule_that_does_not_resolve_in_the_query_stops_the_retries(self) -> None:
        filters = {
            "type": "AND",
            "values": [{"type": "AND", "values": [{"key": "$virt_unknown", "type": "event", "value": "x"}]}],
        }
        ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team,
            label="Unknown",
            filters=filters,
            bytecode=compile_filter_bytecode(self.team.id, filters),
            order_key=2,
        )

        with pytest.raises(ApplicationError) as failure:
            sweep_team_tag_rules_activity(self.inputs)

        assert (failure.value.type, failure.value.non_retryable) == (INVALID_RULE_ERROR_TYPE, True)

    def test_a_full_cluster_is_retried(self) -> None:
        with patch(QUERY, side_effect=ClickHouseClusterMemoryLimitExceeded()):
            with pytest.raises(ClickHouseClusterMemoryLimitExceeded):
                sweep_team_tag_rules_activity(self.inputs)


class TestErrorTrackingTagRuleSweepWorkflow:
    @pytest.mark.asyncio
    async def test_a_failed_team_does_not_stop_the_other_teams(self, caplog: pytest.LogCaptureFixture) -> None:
        # A bad logging call raises only at INFO, so a workflow that logs one would otherwise pass here.
        caplog.set_level(logging.INFO, logger="temporalio.workflow")
        caplog.set_level(logging.INFO, logger="temporalio.activity")
        swept: list[int] = []

        @activity.defn(name="list_tag_rule_teams_activity")
        async def list_teams() -> list[int]:
            return [1, 2, 3]

        @activity.defn(name="sweep_team_tag_rules_activity")
        async def sweep_team(inputs: SweepTeamTagRulesInputs) -> SweepTeamTagRulesResult:
            if inputs.team_id == 1:
                raise ApplicationError("query limit", non_retryable=True)
            swept.append(inputs.team_id)
            return SweepTeamTagRulesResult(dry_run=True, rules_run=1)

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ErrorTrackingTagRuleSweepWorkflow],
                activities=[list_teams, sweep_team],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(WorkflowFailureError) as failure:
                    await env.client.execute_workflow(
                        ErrorTrackingTagRuleSweepWorkflow.run,
                        # One team at a time, so the failed first team would end the run before the others start.
                        TagRuleSweepInputs(max_concurrent_teams=1),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                        execution_timeout=timedelta(minutes=1),
                    )

        assert swept == [2, 3]
        cause = failure.value.cause
        assert isinstance(cause, ApplicationError) and cause.type == FAILED_TEAMS_ERROR_TYPE
        assert "1/3 teams" in str(cause)
