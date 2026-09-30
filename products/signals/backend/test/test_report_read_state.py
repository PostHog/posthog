from posthog.test.base import APIBaseTest

from posthog.models import Team
from posthog.models.user import User

from products.signals.backend.models import SignalReport, SignalReportAction


class TestReportReadState(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team, title="Example report", status=SignalReport.Status.READY
        )
        self.url = f"/api/projects/{self.team.id}/signals/reports/read_state/"

    def test_read_and_unread_are_private_to_user(self):
        body = {"report_ids": [str(self.report.id)]}
        self.assertEqual(self.client.post(self.url, body).json()["states"], {str(self.report.id): False})
        self.assertEqual(self.client.post(self.url, {**body, "read": True}).status_code, 200)
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, body).json()["states"], {str(self.report.id): False})
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url, body).json()["states"], {str(self.report.id): True})
        self.assertEqual(
            self.client.post(self.url, {**body, "read": False}).json()["states"], {str(self.report.id): False}
        )
        self.assertEqual(SignalReportAction.objects.for_team(self.team.id).filter(report=self.report).count(), 1)

    def test_rejects_foreign_or_deleted_reports_without_partial_write(self):
        other_team = Team.objects.create(organization=self.organization)
        foreign = SignalReport.objects.create(team=other_team, title="Other report")
        deleted = SignalReport.objects.create(
            team=self.team, title="Deleted report", status=SignalReport.Status.DELETED
        )
        for inaccessible in (foreign, deleted):
            response = self.client.post(
                self.url, {"report_ids": [str(self.report.id), str(inaccessible.id)], "read": True}
            )
            self.assertEqual(response.status_code, 404)
        self.assertFalse(SignalReportAction.objects.for_team(self.team.id).filter(report=self.report).exists())

    def test_bulk_is_bounded_and_deduplicated(self):
        body = {"report_ids": [str(self.report.id)] * 2, "read": True}
        self.assertEqual(self.client.post(self.url, body).status_code, 200)
        self.assertEqual(
            self.client.post(self.url, {**body, "report_ids": [str(self.report.id)] * 101}).status_code, 400
        )

    def test_unread_filter_uses_the_current_users_state(self):
        other = SignalReport.objects.create(team=self.team, title="Unread report", status=SignalReport.Status.READY)
        self.client.post(self.url, {"report_ids": [str(self.report.id)], "read": True})
        url = f"/api/projects/{self.team.id}/signals/reports/"
        unread = self.client.get(url, {"unread": "true"})
        self.assertEqual(unread.status_code, 200)
        self.assertEqual([item["id"] for item in unread.json()["results"]], [str(other.id)])
        read = self.client.get(url, {"unread": "false"})
        self.assertEqual([item["id"] for item in read.json()["results"]], [str(self.report.id)])
