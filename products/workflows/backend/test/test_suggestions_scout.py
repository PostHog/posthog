from datetime import UTC, datetime, timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import ActivityLog, Team
from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.models import HogFlow, HogFlowOptimization, HogFlowRevision, WorkflowProposal
from products.workflows.backend.services.suggestions_scout import (
    EMAIL_METRICS_MAX_EXECUTION_S,
    suggestions_scout_no_input_reason,
    suggestions_scout_run_reason,
)

SERVICE = "products.workflows.backend.services.suggestions_scout"

NOW = datetime(2026, 10, 9, 12, 30, 0, tzinfo=UTC)
LAST_RUN = NOW - timedelta(hours=24)


@time_machine.travel(NOW, tick=False)
class TestSuggestionsScoutRunReason(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flow = self._flow(self.team, "active")
        self._opt_in(self.flow, days_ago=5)
        self.revision = HogFlowRevision.objects.unscoped().create(
            team=self.team, hog_flow=self.flow, version=2, content={}
        )
        self._age(HogFlowRevision, self.revision.pk, days=4)
        self.proposal = WorkflowProposal.objects.unscoped().create(
            team=self.team,
            hog_flow=self.flow,
            title="Shorter subject",
            rationale="",
            content={},
            base_version=2,
            status="rejected",
            resolved_at=NOW - timedelta(days=3),
        )

    def _flow(self, team: Team, status: str) -> HogFlow:
        return HogFlow.objects.create(team=team, name="Digest", status=status, version=2)

    def _opt_in(self, flow: HogFlow, *, days_ago: float) -> None:
        row = HogFlowOptimization.objects.unscoped().create(team=flow.team, hog_flow=flow, enabled=True)
        self._age(HogFlowOptimization, row.pk, days=days_ago)

    def _age(self, model: type[HogFlowOptimization] | type[HogFlowRevision], pk: UUID, *, days: float) -> None:
        model.objects.unscoped().filter(pk=pk).update(created_at=NOW - timedelta(days=days))

    def _send(
        self,
        flow: HogFlow,
        *,
        hours_ago: float,
        metric: str = "email_sent",
        version: int | None = None,
        instance: str = "step-1",
    ) -> None:
        create_app_metric2(
            team_id=flow.team_id,
            app_source="hog_flow_version",
            app_source_id=f"{flow.id}/{version or flow.version}",
            instance_id=instance,
            metric_kind="email",
            metric_name=metric,
            count=30,
            timestamp=NOW - timedelta(hours=hours_ago),
        )

    def _reason(self, last_run_at: datetime = LAST_RUN) -> str | None:
        return suggestions_scout_run_reason(self.team.pk, last_run_at=last_run_at, now=NOW)

    def test_first_run_always_runs(self) -> None:
        assert suggestions_scout_run_reason(self.team.pk, last_run_at=None, now=NOW) == "first_run"

    def test_nothing_new_skips(self) -> None:
        self._send(self.flow, hours_ago=80)

        assert self._reason() is None

    @parameterized.expand(
        [
            ("published", "published"),
            ("suggestion_resolved", "suggestion_resolved"),
            ("re_enabled", "opted_in"),
            ("newly_opted_in_flow", "opted_in"),
            ("send_matured", "sends_matured"),
            ("archived_workflow_made_live_again", "reactivated"),
            ("first_opens_on_a_mature_version", "first_opens"),
        ]
    )
    def test_new_input_runs(self, change: str, reason: str) -> None:
        if change == "published":
            self._age(HogFlowRevision, self.revision.pk, days=0.1)
        elif change == "suggestion_resolved":
            WorkflowProposal.objects.unscoped().filter(pk=self.proposal.pk).update(resolved_at=NOW - timedelta(hours=2))
        elif change == "re_enabled":
            ActivityLog.objects.create(
                team_id=self.team.pk, scope="HogFlow", activity="optimization_enabled", item_id=str(self.flow.id)
            )
        elif change == "newly_opted_in_flow":
            self._opt_in(self._flow(self.team, "active"), days_ago=0.1)
        elif change == "send_matured":
            self._send(self.flow, hours_ago=50)
        elif change == "archived_workflow_made_live_again":
            ActivityLog.objects.create(
                team_id=self.team.pk,
                scope="HogFlow",
                activity="updated",
                item_id=str(self.flow.id),
                detail={"changes": [{"type": "HogFlow", "action": "changed", "field": "status", "after": "active"}]},
            )
        elif change == "first_opens_on_a_mature_version":
            self._send(self.flow, hours_ago=100)
            self._send(self.flow, hours_ago=2, metric="email_opened")

        assert self._reason() == reason

    def test_quiet_for_a_week_runs(self) -> None:
        assert self._reason(last_run_at=NOW - timedelta(days=7)) == "backstop"

    @parameterized.expand(
        [
            ("send_not_yet_mature", "immature"),
            ("send_from_a_workflow_not_opted_in", "not_opted_in"),
            ("change_to_a_draft_workflow", "draft"),
            ("change_in_another_project", "other_project"),
            ("more_opens_on_a_version_already_opened", "more_opens"),
            ("send_of_a_version_no_longer_live", "old_version"),
            ("workflow_archived", "archived"),
        ]
    )
    def test_changes_the_scout_cannot_read_skip(self, _name: str, case: str) -> None:
        if case == "immature":
            self._send(self.flow, hours_ago=40)
        elif case == "not_opted_in":
            self._send(self._flow(self.team, "active"), hours_ago=50)
        elif case == "draft":
            draft = self._flow(self.team, "draft")
            self._opt_in(draft, days_ago=0.1)
            HogFlowRevision.objects.unscoped().create(team=self.team, hog_flow=draft, version=1, content={})
        elif case == "other_project":
            other_team = Team.objects.create(organization=self.organization, name="Other project")
            other_flow = self._flow(other_team, "active")
            self._opt_in(other_flow, days_ago=0.1)
            self._send(other_flow, hours_ago=50)
        elif case == "more_opens":
            self._send(self.flow, hours_ago=100, metric="email_opened", instance="step-1")
            self._send(self.flow, hours_ago=2, metric="email_opened", instance="step-2")
        elif case == "old_version":
            self._send(self.flow, hours_ago=50, version=1)
        elif case == "archived":
            ActivityLog.objects.create(
                team_id=self.team.pk,
                scope="HogFlow",
                activity="updated",
                item_id=str(self.flow.id),
                detail={"changes": [{"type": "HogFlow", "action": "changed", "field": "status", "after": "archived"}]},
            )

        assert self._reason() is None

    @parameterized.expand(
        [
            ("live_opted_in_workflow", "live", None),
            ("opted_out", "opted_out", "no_opted_in_workflow"),
            ("workflow_archived", "archived", "no_opted_in_workflow"),
            ("only_in_a_child_environment", "child_environment", None),
            ("only_in_another_project", "other_project", "no_opted_in_workflow"),
        ]
    )
    def test_no_input_reason(self, _name: str, case: str, expected: str | None) -> None:
        if case == "archived":
            HogFlow.objects.filter(pk=self.flow.pk).update(status="archived")
        elif case != "live":
            HogFlowOptimization.objects.unscoped().filter(hog_flow=self.flow).update(enabled=False)
        if case == "child_environment":
            environment = Team.objects.create(
                organization=self.organization, project=self.team.project, parent_team=self.team, name="Staging"
            )
            self._opt_in(self._flow(environment, "active"), days_ago=1)
        elif case == "other_project":
            other_team = Team.objects.create(organization=self.organization, name="Other project")
            self._opt_in(self._flow(other_team, "active"), days_ago=1)

        assert suggestions_scout_no_input_reason(self.team.pk) == expected

    def test_reads_workflows_in_every_environment_of_the_project(self) -> None:
        environment = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Staging"
        )
        flow = self._flow(environment, "active")
        self._opt_in(flow, days_ago=5)
        self._send(flow, hours_ago=50)

        with patch(f"{SERVICE}.sync_execute", wraps=sync_execute) as query:
            assert self._reason() == "sends_matured"

        assert sorted(call.kwargs["team_id"] for call in query.call_args_list) == sorted([self.team.pk, environment.pk])
        for call in query.call_args_list:
            assert call.args[1]["team_id"] == call.kwargs["team_id"]
            assert call.kwargs["settings"]["timeout_overflow_mode"] == "throw"
        assert query.call_args_list[1].kwargs["settings"]["max_execution_time"] < EMAIL_METRICS_MAX_EXECUTION_S

    def test_metrics_reads_stop_once_the_budget_is_used(self) -> None:
        environment = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Staging"
        )
        self._opt_in(self._flow(environment, "active"), days_ago=5)
        clock = iter([0.0, EMAIL_METRICS_MAX_EXECUTION_S - 1, EMAIL_METRICS_MAX_EXECUTION_S + 1])

        with (
            patch(f"{SERVICE}.monotonic", side_effect=lambda: next(clock)),
            patch(f"{SERVICE}.sync_execute", wraps=sync_execute) as query,
            self.assertRaises(TimeoutError),
        ):
            self._reason()

        query.assert_called_once()
        assert query.call_args.kwargs["settings"]["max_execution_time"] == 1
