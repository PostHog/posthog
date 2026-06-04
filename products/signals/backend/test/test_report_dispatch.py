import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.tasks.backend.models import Task

FLAG_PATH = "products.signals.backend.views.posthoganalytics.feature_enabled"
START_INTERNAL_PATH = "products.signals.backend.views.start_internal_implementation_task"


class TestReportDispatchEndpoint(APIBaseTest):
    def _url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/dispatch/"

    def _create_report(self, *, with_repo: bool = True) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout 500s",
            summary="Users hit a 500 on the checkout page",
            signal_count=3,
            total_weight=1.5,
        )
        if with_repo:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
                content=json.dumps({"repository": "PostHog/posthog", "reason": "matches the stack trace"}),
            )
        return report

    def test_flag_off_returns_404(self):
        report = self._create_report()
        with patch(FLAG_PATH, return_value=False):
            response = self.client.post(self._url(str(report.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_dispatch_another_teams_report(self):
        other_team = Team.objects.create(organization=Organization.objects.create(name="other-org"), name="other-team")
        other_report = SignalReport.objects.create(
            team=other_team, status=SignalReport.Status.READY, title="x", summary="y", signal_count=1, total_weight=1.0
        )
        with patch(FLAG_PATH, return_value=True):
            response = self.client.post(self._url(str(other_report.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_dispatch_creates_internal_task(self):
        report = self._create_report()
        task = MagicMock(id="task-123")
        with patch(FLAG_PATH, return_value=True), patch(START_INTERNAL_PATH, return_value=task) as mock_start:
            response = self.client.post(self._url(str(report.id)))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"task_id": "task-123", "status": "started"}
        mock_start.assert_called_once()
        assert mock_start.call_args.kwargs["repository"] == "PostHog/posthog"

    def test_without_repository_returns_409(self):
        report = self._create_report(with_repo=False)
        with patch(FLAG_PATH, return_value=True), patch(START_INTERNAL_PATH) as mock_start:
            response = self.client.post(self._url(str(report.id)))
        assert response.status_code == status.HTTP_409_CONFLICT
        mock_start.assert_not_called()

    def test_missing_github_integration_returns_409(self):
        # Task.create_and_run raises ValueError when the team has no GitHub integration; the
        # endpoint must surface it as an actionable 409, not an unhandled 500.
        report = self._create_report()
        with (
            patch(FLAG_PATH, return_value=True),
            patch(START_INTERNAL_PATH, side_effect=ValueError("Team 1 does not have a GitHub integration")),
        ):
            response = self.client.post(self._url(str(report.id)))
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "GitHub integration" in response.json()["error"]

    def test_duplicate_dispatch_is_idempotent(self):
        report = self._create_report()
        task = Task.objects.create(team=self.team, title="t", origin_product=Task.OriginProduct.SIGNAL_REPORT)
        SignalReportTask.objects.create(
            team=self.team,
            report=report,
            task=task,
            relationship=SignalReportTask.Relationship.IMPLEMENTATION,
        )
        with patch(FLAG_PATH, return_value=True), patch(START_INTERNAL_PATH) as mock_start:
            response = self.client.post(self._url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "already_dispatched"
        assert response.json()["task_id"] == str(task.id)
        mock_start.assert_not_called()
