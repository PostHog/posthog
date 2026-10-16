from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models import User

from products.notifications.backend.facade.testing import stored_notifications_for_team
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob

BATCH_DISPATCH = (
    "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
)
CANCEL_BATCH_PROXY = "products.workflows.backend.presentation.views.hog_flow.cancel_hog_flow_batch_job"
SERVICE = "products.workflows.backend.services.batch_job_notifications"


@patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
@patch(f"{SERVICE}.is_email_available", return_value=True)
@patch(f"{SERVICE}.EmailMessage")
class TestWaitingBatchJobNotifications(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.hog_flow = HogFlow.objects.create(
            team=self.team, name="Spring launch", trigger={}, actions=[], edges=[], origin_product="broadcasts"
        )

    def _create_batch_job(self, job_status: str) -> HogFlowBatchJob:
        with patch(BATCH_DISPATCH):
            return HogFlowBatchJob.objects.create(
                team=self.team, hog_flow=self.hog_flow, status=job_status, created_by=self.user
            )

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def _resolver_writes(self, batch_job: HogFlowBatchJob, new_status: str) -> None:
        response = self.client.put(
            f"/api/projects/{self.team.id}/internal/hog_flows/batch_jobs/{batch_job.id}/status",
            {"status": new_status},
            content_type="application/json",
            headers={"x-internal-api-secret": "test-secret-123"},
        )
        assert response.status_code == 200, response.json()

    def _cancel_as(self, user: User, batch_job: HogFlowBatchJob) -> None:
        self.client.force_login(user)
        with patch(CANCEL_BATCH_PROXY, return_value=MagicMock(status_code=200, json=lambda: {"done": True})):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/batch_jobs/{batch_job.id}/cancel/"
            )
        assert response.status_code == 200, response.json()

    def test_a_waiting_run_that_times_out_notifies_its_author(self, mock_email, _mock_available, _mock_flag):
        batch_job = self._create_batch_job("waiting")

        self._resolver_writes(batch_job, "failed")

        [notification] = stored_notifications_for_team(self.team.id)
        assert notification.resolved_user_ids == [self.user.id]
        assert notification.source_url == f"/project/{self.team.id}/broadcasts/{self.hog_flow.id}"
        mock_email.return_value.add_user_recipient.assert_called_once_with(self.user)
        assert mock_email.call_args.kwargs["template_context"]["timed_out"] is True

    @parameterized.expand([("active_run_fails", "active", "failed"), ("waiting_run_completes", "waiting", "completed")])
    def test_other_resolver_writes_do_not_notify(self, mock_email, _a, _f, _name, from_status, to_status):
        self._resolver_writes(self._create_batch_job(from_status), to_status)

        assert stored_notifications_for_team(self.team.id) == []
        mock_email.assert_not_called()

    def test_a_waiting_run_another_member_stops_notifies_its_author(self, mock_email, _mock_available, _mock_flag):
        batch_job = self._create_batch_job("waiting")
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")

        self._cancel_as(teammate, batch_job)

        [notification] = stored_notifications_for_team(self.team.id)
        assert notification.resolved_user_ids == [self.user.id]
        assert mock_email.call_args.kwargs["template_context"]["timed_out"] is False

    @parameterized.expand([("author_stops_waiting_run", "waiting"), ("teammate_stops_active_run", "active")])
    def test_stops_the_author_already_knows_about_do_not_notify(self, mock_email, _a, _f, _name, from_status):
        batch_job = self._create_batch_job(from_status)
        stopper = (
            self.user
            if from_status == "waiting"
            else User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        )

        self._cancel_as(stopper, batch_job)

        assert stored_notifications_for_team(self.team.id) == []
        mock_email.assert_not_called()

    def test_turning_the_email_off_keeps_the_in_app_notification(self, mock_email, _mock_available, _mock_flag):
        self.user.partial_notification_settings = {"workflow_batch_run_not_sent": False}
        self.user.save()

        self._resolver_writes(self._create_batch_job("waiting"), "failed")

        assert len(stored_notifications_for_team(self.team.id)) == 1
        mock_email.assert_not_called()
