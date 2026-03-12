from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team

from products.signals.backend.models import SignalReport


class TestSignalReportDeleteAPI(APIBaseTest):
    def _url(self, report_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/signal_reports/"
        if report_id:
            return f"{base}{report_id}/"
        return base

    def _create_report(self, team=None, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
            signal_count=3,
            total_weight=1.5,
        )

    # --- Delete ---

    @parameterized.expand(
        [
            ("from_ready", SignalReport.Status.READY, status.HTTP_202_ACCEPTED),
            ("from_potential", SignalReport.Status.POTENTIAL, status.HTTP_202_ACCEPTED),
            ("from_candidate", SignalReport.Status.CANDIDATE, status.HTTP_202_ACCEPTED),
            # Suppressed reports are excluded from the base queryset when no status
            # filter is supplied, so detail delete returns 404.
            ("from_suppressed", SignalReport.Status.SUPPRESSED, status.HTTP_404_NOT_FOUND),
            ("from_failed", SignalReport.Status.FAILED, status.HTTP_202_ACCEPTED),
        ]
    )
    def test_delete_report_starts_deletion_workflow(self, _name, initial_status, expected_status):
        report = self._create_report(report_status=initial_status)
        response = self.client.delete(self._url(str(report.id)))
        assert response.status_code == expected_status
        if expected_status == status.HTTP_202_ACCEPTED:
            assert response.json() == {"status": "deletion_started", "report_id": str(report.id)}
        report.refresh_from_db()
        if expected_status == status.HTTP_202_ACCEPTED:
            assert report.status == SignalReport.Status.DELETED
        else:
            assert report.status == initial_status

    def test_deleted_report_excluded_from_list(self):
        report = self._create_report()
        self.client.delete(self._url(str(report.id)))
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert all(r["id"] != str(report.id) for r in response.json()["results"])

    def test_delete_other_teams_report_forbidden(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        report = self._create_report(team=other_team)
        response = self.client.delete(self._url(str(report.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    def test_delete_already_deleted_report_returns_404(self):
        report = self._create_report(report_status=SignalReport.Status.DELETED)
        response = self.client.delete(self._url(str(report.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND
