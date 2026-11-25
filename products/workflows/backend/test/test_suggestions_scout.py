from datetime import UTC, datetime, timedelta
from typing import Any
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
    ) -> None:
        create_app_metric2(
            team_id=flow.team_id,
            app_source="hog_flow_version",
            app_source_id=f"{flow.id}/{version or flow.version}",
            instance_id="step-1",
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

        assert self._reason() == reason

    @parameterized.expand(
        [
            ("runs_finished_their_window", "7d", "event", [("2026-12-12T10:00:00", 25)], "conversions_settled"),
            (
                "enough_runs_only_with_earlier_days",
                "7d",
                "event",
                [("2026-12-01T10:00:00", 19), ("2026-12-12T23:30:00", 1)],
                "conversions_settled",
            ),
            ("already_settled_at_the_last_run", "7d", "event", [("2026-12-11T23:30:00", 25)], None),
            ("still_inside_the_window", "7d", "event", [("2026-12-13T00:10:00", 25)], None),
            ("too_few_runs", "7d", "event", [("2026-12-12T10:00:00", 19)], None),
            ("window_too_long_to_measure", "31d", "event", [("2026-11-18T10:00:00", 25)], None),
            ("no_window_means_ninety_days", None, "event", [("2026-12-12T10:00:00", 25)], None),
            (
                "started_before_conversions_were_recorded",
                "30d",
                "event",
                [("2026-11-12T10:00:00", 25), ("2026-11-19T10:00:00", 1)],
                None,
            ),
            ("webhook_started_before_its_starts_were_versioned", "22d", "webhook", [("2026-11-27T10:00:00", 25)], None),
            ("webhook_counts_from_its_cutoff", "21d", "webhook", [("2026-11-28T10:00:00", 25)], "conversions_settled"),
        ]
    )
    def test_settled_conversions(
        self, _name: str, window: str | None, trigger: str, runs: list[tuple[str, int]], expected: str | None
    ) -> None:
        self._set_goal(self.flow, window, trigger=trigger)
        for started_at, count in runs:
            self._start_runs(self.flow, started_at, count)

        assert self._reason_in_december() == expected

    @parameterized.expand(
        [
            ("runs_of_a_version_no_longer_live", "old_version", None),
            ("no_email_step_to_change", "no_email_step", None),
            ("only_the_draft_has_a_goal", "revision_without_goal", None),
            ("version_without_a_revision", "no_revision", "conversions_settled"),
            ("another_workflow_has_the_shorter_window", "other_window", None),
            ("workflow_in_a_child_environment", "child_environment", "conversions_settled"),
        ]
    )
    def test_settled_conversions_read_the_live_version(self, _name: str, case: str, expected: str | None) -> None:
        flow = self.flow
        if case == "child_environment":
            environment = Team.objects.create(
                organization=self.organization, project=self.team.project, parent_team=self.team, name="Staging"
            )
            flow = self._flow(environment, "active")
            self._opt_in(flow, days_ago=5)
        self._set_goal(flow, "14d" if case == "other_window" else "7d")
        if case == "no_email_step":
            HogFlow.objects.filter(pk=flow.pk).update(actions=[{"id": "step-1", "type": "function"}])
        elif case == "revision_without_goal":
            HogFlowRevision.objects.unscoped().filter(hog_flow=flow).update(content={"conversion": None})
        elif case == "no_revision":
            HogFlowRevision.objects.unscoped().filter(hog_flow=flow).delete()
        elif case == "other_window":
            other = self._flow(self.team, "active")
            self._opt_in(other, days_ago=5)
            self._set_goal(other, "7d")
        self._start_runs(flow, "2026-12-12T10:00:00", 25, version=1 if case == "old_version" else None)

        assert self._reason_in_december() == expected

    def _set_goal(self, flow: HogFlow, window: str | None, *, trigger: str = "event") -> None:
        conversion: dict[str, Any] = {"filters": [], "events": [{"filters": {"events": [{"id": "paid"}]}}]}
        if window:
            conversion["window"] = window
        HogFlow.objects.filter(pk=flow.pk).update(
            conversion=conversion, trigger={"type": trigger}, actions=[{"id": "step-1", "type": "function_email"}]
        )
        HogFlowRevision.objects.unscoped().filter(hog_flow=flow).update(
            content={"conversion": conversion, "trigger": {"type": trigger}}
        )

    def _start_runs(self, flow: HogFlow, started_at: str, count: int, *, version: int | None = None) -> None:
        create_app_metric2(
            team_id=flow.team_id,
            app_source="hog_flow_version",
            app_source_id=f"{flow.id}/{version or flow.version}",
            instance_id="trigger",
            metric_kind="other",
            metric_name="triggered",
            count=count,
            timestamp=datetime.fromisoformat(started_at).replace(tzinfo=UTC),
        )

    def _reason_in_december(self) -> str | None:
        now = datetime(2026, 12, 20, 12, 30, tzinfo=UTC)
        return suggestions_scout_run_reason(self.team.pk, last_run_at=now - timedelta(hours=24), now=now)

    def test_quiet_for_a_week_runs(self) -> None:
        assert self._reason(last_run_at=NOW - timedelta(days=7)) == "backstop"

    @parameterized.expand(
        [
            ("send_not_yet_mature", "immature"),
            ("send_from_a_workflow_not_opted_in", "not_opted_in"),
            ("change_to_a_draft_workflow", "draft"),
            ("change_in_another_project", "other_project"),
            ("send_of_a_version_no_longer_live", "old_version"),
            ("opens_without_a_matured_send", "opens"),
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
        elif case == "old_version":
            self._send(self.flow, hours_ago=50, version=1)
        elif case == "opens":
            self._send(self.flow, hours_ago=2, metric="email_opened")

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
