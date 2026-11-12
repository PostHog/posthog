from __future__ import annotations

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.models import SignalReport
from products.signals.backend.task_run_artefacts import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_DISCUSSION,
    append_task_run_artefact,
)
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.tasks.backend.models import Task, TaskRun

_QUESTION = "Is this expected?"


class TestScoutReportDiscussionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/signals/scout/report_discussions/"
        self.authored = SignalReport.objects.create(team=self.team, title="Checkout errors", status="ready")
        self.edited = SignalReport.objects.create(team=self.team, title="Slow dashboards", status="ready")
        self.run = _make_run(
            self.team, emitted_report_ids=[str(self.authored.id)], edited_report_ids=[str(self.edited.id)]
        )

    def _discussion(
        self,
        report: SignalReport,
        *,
        state: dict | None = None,
        team: Team | None = None,
        created_by: User | None = None,
    ) -> Task:
        task = Task.objects.create(
            team=team or self.team,
            title="Discuss report",
            description=f"Let's discuss this PostHog Inbox report: https://example.com/r/{report.id}\n\n{_QUESTION}",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            created_by=created_by or self.user,
        )
        TaskRun.objects.create(task=task, team=team or self.team, state=state or {})
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_DISCUSSION,
            task_id=str(task.id),
        )
        return task

    def test_lists_discussions_on_own_reports_only(self) -> None:
        authored_task = self._discussion(self.authored, state={"task_summary": "Intended behavior."})
        edited_task = self._discussion(self.edited, state={"task_summary": "Fix shipped."})
        sibling_report = SignalReport.objects.create(team=self.team, title="Sibling", status="ready")
        _make_run(self.team, skill_name="signals-scout-other", emitted_report_ids=[str(sibling_report.id)])
        self._discussion(sibling_report, state={"task_summary": "Not yours."})
        _authenticate_as_scout(self, sandbox_task_id=self.run.task_run.task_id)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        rows = {row["task_id"]: row for row in response.json()}
        assert set(rows) == {str(authored_task.id), str(edited_task.id)}
        assert rows[str(authored_task.id)]["involvement"] == "authored"
        assert rows[str(authored_task.id)]["task_summary"] == "Intended behavior."
        assert rows[str(authored_task.id)]["question"] == _QUESTION
        assert rows[str(edited_task.id)]["involvement"] == "edited"

    @parameterized.expand(
        [
            ("prior_run_summary", {"prior_run_summary": "Earlier outcome."}, "Earlier outcome."),
            (
                "analytics_context_is_private",
                {"task_summary": "Private outcome.", "analytics_query_context": [{"kind": "HogQLQuery"}]},
                None,
            ),
        ]
    )
    def test_summary_follows_task_visibility(self, _name: str, state: dict, expected: str | None) -> None:
        self._discussion(self.authored, state=state)
        _authenticate_as_scout(self, sandbox_task_id=self.run.task_run.task_id)

        [row] = self.client.get(self.url).json()

        assert row["task_summary"] == expected

    def test_question_is_withheld_when_the_asker_cannot_steer_scouts(self) -> None:
        outsider = User.objects.create_and_join(
            Organization.objects.create(name="Elsewhere"), "outsider@example.com", None
        )
        self._discussion(self.authored, state={"task_summary": "Intended behavior."}, created_by=outsider)
        _authenticate_as_scout(self, sandbox_task_id=self.run.task_run.task_id)

        [row] = self.client.get(self.url).json()

        assert row["question"] is None
        assert row["task_summary"] == "Intended behavior."

    def test_child_environment_discussion_is_not_returned(self) -> None:
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        self._discussion(self.authored, state={"task_summary": "From the child."}, team=env)
        _authenticate_as_scout(self, sandbox_task_id=self.run.task_run.task_id)

        assert self.client.get(self.url).json() == []

    def test_refuses_a_caller_that_is_not_a_scout_run(self) -> None:
        self._discussion(self.authored, state={"task_summary": "Intended behavior."})
        _authenticate_as_scout(self)

        assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN
