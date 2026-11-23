import uuid
import dataclasses
from collections.abc import Callable
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.db.models import F
from django.utils import timezone

from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.logic import team_flags
from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG, RULE_SWEEP_WRITES_FLAG
from products.error_tracking.backend.logic.issue_tags.sweep import (
    RuleSweep,
    TagRuleSweepSkipReason,
    TeamTagRuleSweep,
    sweep_team_tag_rules,
)
from products.error_tracking.backend.logic.rules import compile_filter_bytecode
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueTag,
    ErrorTrackingIssueTagRule,
    sync_issues_to_clickhouse,
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

Source = ErrorTrackingIssueTag.Source

QUERY = "products.error_tracking.backend.logic.issue_tags.sweep.execute_hogql_query"
CHECKOUT_RULE_FILTERS = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [{"key": "$pathname", "type": "event", "operator": "icontains", "value": "/checkout"}],
        }
    ],
}


class TestSweepTeamTagRules(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enabled_flags = {ISSUE_TAGS_FLAG, RULE_SWEEP_WRITES_FLAG}
        flags = patch.object(
            team_flags, "feature_enabled_or_false", new=lambda flag, *args, **kwargs: flag in self.enabled_flags
        )
        flags.start()
        self.addCleanup(flags.stop)
        self.rule = self._rule(CHECKOUT_RULE_FILTERS)
        self.end = timezone.now()

    def test_labels_an_issue_whose_later_exception_matches(self) -> None:
        later_match = self._issue()
        self._exception(later_match, "/home", hours_ago=3)
        self._exception(later_match, "/checkout/pay", hours_ago=2)
        no_match = self._issue()
        self._exception(no_match, "/home", hours_ago=2)
        match_before_window = self._issue()
        self._exception(match_before_window, "/checkout/pay", hours_ago=30)
        flush_persons_and_events()

        result = self._sweep()

        assert result == self._result(dry_run=False, matching=1, to_write=1, written=1)
        assert self._answers() == [(later_match.id, self.rule.key, True, Source.RULE, str(self.rule.id), 1)]

    def test_a_dry_run_counts_the_labels_and_writes_none(self) -> None:
        self.enabled_flags.remove(RULE_SWEEP_WRITES_FLAG)
        issue = self._issue()
        self._exception(issue, "/checkout/pay", hours_ago=2)
        flush_persons_and_events()

        result = self._sweep()

        assert result == self._result(dry_run=True, matching=1, to_write=1, written=0)
        assert self._answers() == []

    def test_a_person_who_removed_the_label_keeps_the_answer(self) -> None:
        issue = self._issue()
        self._exception(issue, "/checkout/pay", hours_ago=2)
        flush_persons_and_events()
        ErrorTrackingIssueTag.objects.for_team(self.team.id).create(
            team=self.team, issue=issue, key=self.rule.key, value=False, source=Source.MANUAL, question_version=1
        )

        result = self._sweep()

        assert result == self._result(dry_run=False, matching=1, to_write=0, written=0)
        assert self._answers() == [(issue.id, self.rule.key, False, Source.MANUAL, None, 1)]

    @parameterized.expand(
        [
            ("deleted", lambda rules: rules.delete()),
            ("edited", lambda rules: rules.update(version=F("version") + 1)),
            ("disabled", lambda rules: rules.update(disabled_data={"message": "broken"})),
        ]
    )
    def test_a_rule_changed_during_the_run_writes_nothing(self, _name: str, change: Callable[[object], object]) -> None:
        issue = self._issue()
        self._exception(issue, "/checkout/pay", hours_ago=2)
        flush_persons_and_events()
        rules = ErrorTrackingIssueTagRule.objects.for_team(self.team.id).filter(id=self.rule.id)

        # The sweep reports progress after its query and before its writes, which is where a person's change lands.
        result = self._sweep(on_progress=lambda: change(rules))

        assert isinstance(result, TeamTagRuleSweep) and result.rules[0].labels_written == 0
        assert self._answers() == []

    def test_a_team_without_issue_tags_reads_no_rule_or_event(self) -> None:
        self.enabled_flags.clear()

        with self.assertNumQueries(0), patch(QUERY, side_effect=AssertionError("flag is off, so no event read")):
            result = self._sweep()

        assert result == TagRuleSweepSkipReason.DISABLED

    def test_a_rule_on_the_exception_list_is_skipped_without_a_query(self) -> None:
        self.rule.delete()
        self._rule(
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "$exception_list", "type": "event", "operator": "icontains", "value": "Timeout"}
                        ],
                    }
                ],
            }
        )

        with patch(QUERY, side_effect=AssertionError("the only rule is skipped, so no event read")):
            result = self._sweep()

        assert isinstance(result, TeamTagRuleSweep)
        assert (result.rules, result.rules_skipped) == ((), 1)

    def _sweep(self, on_progress: Callable[[], object] = lambda: None) -> TeamTagRuleSweep | TagRuleSweepSkipReason:
        result = sweep_team_tag_rules(
            self.team.id, start=self.end - SWEEP_WINDOW, end=self.end, on_progress=on_progress
        )
        # The measured query time differs on every run.
        if isinstance(result, TeamTagRuleSweep):
            return dataclasses.replace(result, query_duration=timedelta(0))
        return result

    def _result(self, *, dry_run: bool, matching: int, to_write: int, written: int) -> TeamTagRuleSweep:
        return TeamTagRuleSweep(
            dry_run=dry_run,
            rules=(
                RuleSweep(
                    rule_id=self.rule.id, matching_issues=matching, labels_to_write=to_write, labels_written=written
                ),
            ),
            rules_skipped=0,
            matching_issues=matching,
            truncated=False,
            query_duration=timedelta(0),
        )

    def _rule(self, filters: dict) -> ErrorTrackingIssueTagRule:
        return ErrorTrackingIssueTagRule.objects.for_team(self.team.id).create(
            team=self.team,
            label="Checkout",
            filters=filters,
            bytecode=compile_filter_bytecode(self.team.id, filters),
            order_key=1,
        )

    def _issue(self) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team, issue=issue, fingerprint=f"fingerprint-{issue.id}"
        )
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.id)
        return issue

    def _exception(self, issue: ErrorTrackingIssue, pathname: str, *, hours_ago: int) -> None:
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id="user",
            properties={
                "$exception_issue_id": str(issue.id),
                "$exception_fingerprint": f"fingerprint-{issue.id}",
                "$pathname": pathname,
            },
            timestamp=self.end - timedelta(hours=hours_ago),
        )

    def _answers(self) -> list[tuple[uuid.UUID, str, bool | None, str, str | None, int]]:
        tags = ErrorTrackingIssueTag.objects.for_team(self.team.id).order_by("issue_id", "key")
        return list(tags.values_list("issue_id", "key", "value", "source", "model", "question_version"))


class TestErrorTrackingTagRuleSweepWorkflow:
    @pytest.mark.asyncio
    async def test_a_failed_team_does_not_stop_the_other_teams(self) -> None:
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
                    )

        assert swept == [2, 3]
        cause = failure.value.cause
        assert isinstance(cause, ApplicationError) and cause.type == FAILED_TEAMS_ERROR_TYPE
        assert "1/3 teams" in str(cause)
