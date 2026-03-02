from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team

from products.signals.backend.models import SignalReport


class TestSignalReportAPI(APIBaseTest):
    def _url(self, report_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/signal_reports/"
        if report_id:
            return f"{base}{report_id}/"
        return base

    def _make_report(self, **kwargs) -> SignalReport:
        defaults = {
            "status": SignalReport.Status.READY,
            "title": "Test report",
            "summary": "A test summary",
            "total_weight": 1.5,
            "signal_count": 5,
        }
        return SignalReport.objects.create(team=self.team, **{**defaults, **kwargs})

    def test_list_signal_reports(self):
        self._make_report()
        self._make_report(title="Second report")
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2

    def test_list_excludes_other_teams(self):
        self._make_report()
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_retrieve_signal_report(self):
        report = self._make_report()
        response = self.client.get(self._url(str(report.id)))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(report.id)
        assert data["title"] == "Test report"
        assert data["status"] == "ready"

    def test_retrieve_other_teams_report_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY)
        response = self.client.get(self._url(str(report.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_patch_other_teams_report_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY)
        response = self.client.patch(self._url(str(report.id)), data={"status": "dismissed"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_dismiss_signal_report(self):
        report = self._make_report()
        response = self.client.patch(self._url(str(report.id)), data={"status": "dismissed"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "dismissed"
        report.refresh_from_db()
        assert report.status == SignalReport.Status.DISMISSED

    def test_revert_dismissed_signal_report(self):
        report = self._make_report(status=SignalReport.Status.DISMISSED)
        response = self.client.patch(self._url(str(report.id)), data={"status": "ready"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "ready"
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    def test_readonly_fields_cannot_be_updated(self):
        report = self._make_report()
        response = self.client.patch(
            self._url(str(report.id)),
            data={"title": "HACKED", "summary": "HACKED", "total_weight": 9999, "signal_count": 9999},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["title"] == "Test report"
        assert data["summary"] == "A test summary"
        assert data["total_weight"] == 1.5
        assert data["signal_count"] == 5
        report.refresh_from_db()
        assert report.title == "Test report"
        assert report.total_weight == 1.5
        assert report.signal_count == 5

    def test_status_filter_single(self):
        ready = self._make_report(status=SignalReport.Status.READY)
        self._make_report(status=SignalReport.Status.DISMISSED)
        response = self.client.get(self._url(), {"status": "ready"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["id"] == str(ready.id)

    def test_status_filter_multiple_comma_separated(self):
        self._make_report(status=SignalReport.Status.READY)
        self._make_report(status=SignalReport.Status.DISMISSED)
        self._make_report(status=SignalReport.Status.FAILED)
        response = self.client.get(self._url(), {"status": "ready,dismissed"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2

    def test_status_filter_dismissed(self):
        self._make_report(status=SignalReport.Status.READY)
        dismissed = self._make_report(status=SignalReport.Status.DISMISSED)
        response = self.client.get(self._url(), {"status": "dismissed"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["id"] == str(dismissed.id)

    def test_search_by_title(self):
        match = self._make_report(title="Kafka consumer timeout issue")
        self._make_report(title="Redis connection failure")
        response = self.client.get(self._url(), {"search": "kafka"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["id"] == str(match.id)

    def test_search_by_summary(self):
        match = self._make_report(summary="Plugin server ignores environment variables")
        self._make_report(summary="Cymbal container fails to start")
        response = self.client.get(self._url(), {"search": "environment"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["id"] == str(match.id)

    def test_search_is_case_insensitive(self):
        self._make_report(title="Kafka Consumer Timeout")
        response = self.client.get(self._url(), {"search": "KAFKA"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_ordering_by_total_weight(self):
        low = self._make_report(total_weight=1.0, signal_count=1)
        high = self._make_report(total_weight=10.0, signal_count=1)
        response = self.client.get(self._url(), {"ordering": "-total_weight"})
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(high.id)) < ids.index(str(low.id))

    def test_ordering_by_signal_count(self):
        few = self._make_report(signal_count=2, total_weight=1.0)
        many = self._make_report(signal_count=20, total_weight=1.0)
        response = self.client.get(self._url(), {"ordering": "-signal_count"})
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert ids.index(str(many.id)) < ids.index(str(few.id))

    @parameterized.expand(
        [
            ("ready_to_dismissed", SignalReport.Status.READY, "dismissed", True),
            ("dismissed_to_ready", SignalReport.Status.DISMISSED, "ready", True),
            ("ready_noop", SignalReport.Status.READY, "ready", True),
            ("dismissed_noop", SignalReport.Status.DISMISSED, "dismissed", True),
            ("failed_to_dismissed", SignalReport.Status.FAILED, "dismissed", False),
            ("ready_to_failed", SignalReport.Status.READY, "failed", False),
            ("dismissed_to_failed", SignalReport.Status.DISMISSED, "failed", False),
            ("candidate_to_dismissed", SignalReport.Status.CANDIDATE, "dismissed", False),
        ]
    )
    def test_status_transition(self, _name, from_status, to_status, allowed):
        report = self._make_report(status=from_status)
        response = self.client.patch(self._url(str(report.id)), data={"status": to_status}, format="json")
        expected = status.HTTP_200_OK if allowed else status.HTTP_400_BAD_REQUEST
        assert response.status_code == expected, response.json()

    def test_unauthenticated_request_rejected(self):
        self.client.logout()
        response = self.client.get(self._url())
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
