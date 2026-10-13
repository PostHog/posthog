from datetime import UTC, datetime, timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.models import ActivityLog, Team
from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.models import HogFlow, HogFlowOptimization, HogFlowRevision, WorkflowProposal
from products.workflows.backend.services.suggestions_scout import suggestions_scout_run_reason

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

    def _send(self, flow: HogFlow, *, hours_ago: float, instance: str = "step-1") -> None:
        create_app_metric2(
            team_id=flow.team_id,
            app_source="hog_flow_version",
            app_source_id=f"{flow.id}/{flow.version}",
            instance_id=instance,
            metric_kind="email",
            metric_name="email_sent",
            count=30,
            timestamp=NOW - timedelta(hours=hours_ago),
        )

    def _reason(self) -> str | None:
        return suggestions_scout_run_reason(self.team.pk, last_run_at=LAST_RUN, now=NOW)

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
            ("send_not_yet_mature", "immature"),
            ("send_from_a_workflow_not_opted_in", "not_opted_in"),
            ("change_to_a_draft_workflow", "draft"),
            ("change_in_another_project", "other_project"),
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

        assert self._reason() is None

    def test_reads_workflows_in_every_environment_of_the_project(self) -> None:
        environment = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Staging"
        )
        flow = self._flow(environment, "active")
        self._opt_in(flow, days_ago=5)
        self._send(flow, hours_ago=50)

        assert self._reason() == "sends_matured"
