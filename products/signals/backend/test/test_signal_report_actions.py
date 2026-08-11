from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal

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

    @parameterized.expand(
        [
            ("viewed", None, status.HTTP_204_NO_CONTENT),
            ("feedback", {"sentiment": "positive"}, status.HTTP_200_OK),
        ]
    )
    def test_non_session_credentials_record_no_action(
        self, action_path: str, body: dict | None, expected_status: int
    ) -> None:
        # A personal API key (like a sandbox agent's OAuth token) authenticates *as* its owning
        # user, so a request.user check alone would count automated traffic as a person reading —
        # letting a scout manufacture the consumption evidence that keeps it from being paused.
        report = self._create_report()
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="test", secure_value=hash_key_value(token), scopes=["task:write"]
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/signals/reports/{report.pk}/{action_path}/",
            body,
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == expected_status
        assert not SignalReportAction.objects.filter(report=report).exists()

    @parameterized.expand(
        [
            ("viewed", None, status.HTTP_204_NO_CONTENT),
            ("feedback", {"sentiment": "positive"}, status.HTTP_200_OK),
        ]
    )
    @patch("products.signals.backend.views.is_impersonated_session", return_value=True)
    def test_an_impersonated_session_records_no_action(
        self, action_path: str, body: dict | None, expected_status: int, _mock_impersonated: MagicMock
    ) -> None:
        # Staff impersonation passes the session check while request.user is the customer, so
        # without the impersonation guard a support investigation would write consumption evidence
        # in that customer's name and rescue a scout nobody on their team read.
        report = self._create_report()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/signals/reports/{report.pk}/{action_path}/",
            body,
            format="json",
        )

        assert response.status_code == expected_status
        assert not SignalReportAction.objects.filter(report=report).exists()

    def test_a_suppressed_report_still_records_its_view(self) -> None:
        # The Dismissed tab renders the same detail view, so its opens must count too instead of
        # 404ing like mutating-by-ID actions on suppressed reports do.
        report = self._create_report(status=SignalReport.Status.SUPPRESSED)

        response = self.client.post(self._viewed_url(str(report.pk)))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert SignalReportAction.objects.filter(report=report, user=self.user).exists()
