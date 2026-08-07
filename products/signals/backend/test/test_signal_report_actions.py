from posthog.test.base import APIBaseTest

from rest_framework import status

from products.signals.backend.models import SignalReport, SignalReportAction


class TestSignalReportViewedEndpoint(APIBaseTest):
    def _viewed_url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.pk}/signals/reports/{report_id}/viewed/"

    def _create_report(self, **overrides) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=overrides.pop("status", SignalReport.Status.READY),
            title="Checkout errors spiked",
            summary="Test summary",
            **overrides,
        )

    def test_a_view_is_recorded_once_per_person_and_repeats_bump_the_row(self) -> None:
        report = self._create_report()

        first = self.client.post(self._viewed_url(str(report.pk)))
        assert first.status_code == status.HTTP_204_NO_CONTENT
        action = SignalReportAction.objects.get(report=report, user=self.user)
        assert action.type == SignalReportAction.ActionType.VIEW
        assert action.count == 1
        first_seen = action.last_at

        assert self.client.post(self._viewed_url(str(report.pk))).status_code == status.HTTP_204_NO_CONTENT
        action.refresh_from_db()
        assert action.count == 2
        assert action.last_at > first_seen

    def test_a_suppressed_report_still_records_its_view(self) -> None:
        # The Dismissed tab renders the same detail view, so its opens must count too instead of
        # 404ing like mutating-by-ID actions on suppressed reports do.
        report = self._create_report(status=SignalReport.Status.SUPPRESSED)

        response = self.client.post(self._viewed_url(str(report.pk)))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert SignalReportAction.objects.filter(report=report, user=self.user).exists()
