from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.models import SignalReport


class TestReportLocation(APIBaseTest):
    def _locate(self, report_id: str) -> int | None:
        response = self.client.get(f"/api/projects/{self.team.id}/signals/reports/locate/", {"report_id": report_id})
        self.assertEqual(response.status_code, 200)
        return response.json()["team_id"]

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY, True),
            ("suppressed", SignalReport.Status.SUPPRESSED, True),
            ("deleted", SignalReport.Status.DELETED, False),
        ]
    )
    def test_finds_report_in_other_accessible_project(self, _name: str, status: str, found: bool) -> None:
        other_team = Team.objects.create(organization=self.organization)
        report = SignalReport.objects.create(team=other_team, title="Example report", status=status)
        self.assertEqual(self._locate(str(report.id)), other_team.id if found else None)

    def test_hides_report_in_inaccessible_project(self) -> None:
        foreign_team = Team.objects.create(organization=Organization.objects.create(name="Other org"))
        report = SignalReport.objects.create(team=foreign_team, title="Example report")
        self.assertIsNone(self._locate(str(report.id)))
        self.assertIsNone(self._locate(str(uuid4())))

    def test_personal_api_key_cannot_look_across_projects(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        report = SignalReport.objects.create(team=other_team, title="Example report")
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Task key", user=self.user, secure_value=hash_key_value(raw_key), scopes=["task:read"]
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        self.assertIsNone(self._locate(str(report.id)))
