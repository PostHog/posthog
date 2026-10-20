from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.user import User

from products.signals.backend.models import SignalReport, SignalReportAction
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run


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

    @parameterized.expand([(private, read) for private in (False, True) for read in (None, True, False)])
    def test_scout_read_state_preserves_trial_isolation(self, private: bool, read: bool | None) -> None:
        initial_read = read is False
        action = SignalReportAction.objects.for_team(self.team.id).create(
            team=self.team,
            report=self.report,
            user=self.user,
            type=SignalReportAction.ActionType.READ,
            metadata={"read": initial_read},
            last_at=timezone.now(),
        )
        run = _make_run(
            self.team,
            metadata={"scout_trial": {"version": 1, "context_id": str(uuid4())}} if private else {},
        )
        _authenticate_as_scout(
            self,
            scopes="signals_scout_experiment" if private else "signals_scout",
            sandbox_task_id=run.task_run.task_id,
        )
        body: dict[str, object] = {"report_ids": [str(self.report.id)]}
        if read is not None:
            body["read"] = read

        response = self.client.post(self.url, body)

        denied = private and read is not None
        assert response.status_code == (403 if denied else 200), response.data
        expected_read = initial_read if denied or read is None else read
        if not denied:
            assert response.json()["states"] == {str(self.report.id): expected_read}
        action.refresh_from_db()
        assert action.metadata == {"read": expected_read}

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
