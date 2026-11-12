from __future__ import annotations

from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.signals.backend.models import SignalReport
from products.signals.backend.task_run_artefacts import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_DISCUSSION,
    append_task_run_artefact,
)
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.tasks.backend.models import Channel, Task, TaskRun


class TestScoutReportDiscussionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/signals/scout/report_discussions/"
        self.channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)
        self.authored = SignalReport.objects.create(team=self.team, title="Checkout errors", status="ready")
        self.edited = SignalReport.objects.create(team=self.team, title="Slow dashboards", status="ready")
        self.scout_run = _make_run(
            self.team, emitted_report_ids=[str(self.authored.id)], edited_report_ids=[str(self.edited.id)]
        )

    def _discussion(
        self,
        report: SignalReport,
        *,
        state: dict,
        team: Team | None = None,
        created_by: User | None = None,
        in_channel: bool = True,
    ) -> Task:
        task = Task.objects.create(
            team=team or self.team,
            title="Discuss report",
            description=f"Let's discuss this PostHog Inbox report: https://example.com/r/{report.id}\n\nIs this expected?",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            created_by=created_by or self.user,
            channel=self.channel if in_channel else None,
        )
        TaskRun.objects.create(task=task, team=team or self.team, state=state)
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_DISCUSSION,
            task_id=str(task.id),
        )
        return task

    def _list(self) -> list[dict]:
        _authenticate_as_scout(self, sandbox_task_id=self.scout_run.task_run.task_id)
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def test_lists_discussions_on_own_reports_only(self) -> None:
        authored_task = self._discussion(self.authored, state={"task_summary": "Intended behavior."})
        edited_task = self._discussion(self.edited, state={"task_summary": "Fix shipped."})
        sibling_report = SignalReport.objects.create(team=self.team, title="Sibling", status="ready")
        _make_run(self.team, skill_name="signals-scout-other", emitted_report_ids=[str(sibling_report.id)])
        self._discussion(sibling_report, state={"task_summary": "Not yours."})

        rows = {row["task_id"]: row for row in self._list()}

        assert set(rows) == {str(authored_task.id), str(edited_task.id)}
        assert rows[str(authored_task.id)]["involvement"] == "authored"
        assert rows[str(authored_task.id)]["task_summary"] == "Intended behavior."
        assert "question" not in rows[str(authored_task.id)]
        assert rows[str(edited_task.id)]["involvement"] == "edited"

    @parameterized.expand(
        [
            ("prior_run_summary", {"prior_run_summary": "Earlier outcome."}, True, False, "Earlier outcome."),
            (
                "analytics_context_is_private",
                {"task_summary": "Private outcome.", "analytics_query_context": [{"kind": "HogQLQuery"}]},
                True,
                False,
                None,
            ),
            ("channel_less_task", {"task_summary": "Intended behavior."}, False, False, "Intended behavior."),
            ("creator_cannot_steer_scouts", {"task_summary": "From an outsider."}, False, True, None),
        ]
    )
    def test_summary_is_returned_only_when_safe(
        self, _name: str, state: dict, in_channel: bool, outsider: bool, expected: str | None
    ) -> None:
        created_by = (
            User.objects.create_and_join(Organization.objects.create(name="Elsewhere"), "outsider@example.com", None)
            if outsider
            else None
        )
        task = self._discussion(self.authored, state=state, in_channel=in_channel, created_by=created_by)

        [row] = self._list()

        assert row["task_id"] == str(task.id)
        assert row["task_summary"] == expected

    def test_since_keeps_a_discussion_that_concluded_after_it(self) -> None:
        three_days_ago = timezone.now() - timedelta(days=3)
        concluded = self._discussion(self.authored, state={"task_summary": "Concluded later."})
        stale = self._discussion(self.authored, state={"task_summary": "Concluded long ago."})
        Task.objects.filter(id__in=[concluded.id, stale.id]).update(created_at=three_days_ago)
        TaskRun.objects.filter(task=stale).update(created_at=three_days_ago, updated_at=three_days_ago)
        _authenticate_as_scout(self, sandbox_task_id=self.scout_run.task_run.task_id)

        response = self.client.get(self.url, {"since": (timezone.now() - timedelta(days=1)).isoformat()})

        assert [row["task_id"] for row in response.json()] == [str(concluded.id)]

    def test_child_environment_discussion_is_not_returned(self) -> None:
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        self._discussion(self.authored, state={"task_summary": "From the child."}, team=env)

        assert self._list() == []

    def test_nothing_is_returned_when_the_run_may_not_read_reports(self) -> None:
        self._discussion(self.authored, state={"task_summary": "Intended behavior."})

        real_check = UserAccessControl.check_access_level_for_resource

        def deny_tasks(access: UserAccessControl, resource: APIScopeObject, required_level: AccessControlLevel) -> bool:
            return False if resource == "task" else real_check(access, resource, required_level)

        with patch.object(UserAccessControl, "check_access_level_for_resource", autospec=True, side_effect=deny_tasks):
            assert self._list() == []

    def test_refuses_a_caller_that_is_not_a_scout_run(self) -> None:
        self._discussion(self.authored, state={"task_summary": "Intended behavior."})
        _authenticate_as_scout(self)

        assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN
