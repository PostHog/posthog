import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.models.hog_flow.hog_flow import HogFlow

from products.notifications.backend.facade.enums import (
    NotificationOnlyResourceType,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
)
from products.workflows.backend.services.rate_limit_notifications import handle_workflow_rate_limited


class TestHandleWorkflowRateLimited(APIBaseTest):
    @patch("products.workflows.backend.services.rate_limit_notifications.create_notification")
    def test_sends_notification_with_correct_data(self, mock_create):
        hog_flow = HogFlow.objects.create(
            team=self.team,
            name="My Workflow",
            status="active",
            created_by=self.user,
            trigger={"type": "event", "filters": {}},
            actions=[],
        )

        handle_workflow_rate_limited(
            team_id=self.team.id,
            hog_flow_id=str(hog_flow.id),
            hog_flow_name="My Workflow",
            created_by_id=self.user.id,
        )

        mock_create.assert_called_once()
        data = mock_create.call_args[0][0]
        assert data.team_id == self.team.id
        assert data.notification_type == NotificationType.WORKFLOW_RATE_LIMITED
        assert data.priority == Priority.CRITICAL
        assert data.title == "Workflow 'My Workflow' is being rate limited"
        assert data.target_type == TargetType.USER
        assert data.target_id == str(self.user.id)
        assert data.resource_type == NotificationOnlyResourceType.WORKFLOW
        assert data.resource_id == str(hog_flow.id)
        assert data.source_url == f"/workflows/{hog_flow.id}/workflow"
        assert data.source_type == SourceType.WORKFLOW

    @patch("products.workflows.backend.services.rate_limit_notifications.create_notification")
    def test_resolves_created_by_from_db_when_not_provided(self, mock_create):
        hog_flow = HogFlow.objects.create(
            team=self.team,
            name="My Workflow",
            status="active",
            created_by=self.user,
            trigger={"type": "event", "filters": {}},
            actions=[],
        )

        handle_workflow_rate_limited(
            team_id=self.team.id,
            hog_flow_id=str(hog_flow.id),
            hog_flow_name="My Workflow",
            created_by_id=None,
        )

        mock_create.assert_called_once()
        data = mock_create.call_args[0][0]
        assert data.target_id == str(self.user.id)

    @patch("products.workflows.backend.services.rate_limit_notifications.create_notification")
    def test_skips_when_hogflow_not_found(self, mock_create):
        handle_workflow_rate_limited(
            team_id=self.team.id,
            hog_flow_id=str(uuid.uuid4()),
            hog_flow_name="Missing Workflow",
            created_by_id=None,
        )

        mock_create.assert_not_called()

    @patch("products.workflows.backend.services.rate_limit_notifications.create_notification")
    def test_skips_when_no_created_by(self, mock_create):
        hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Orphan Workflow",
            status="active",
            created_by=None,
            trigger={"type": "event", "filters": {}},
            actions=[],
        )

        handle_workflow_rate_limited(
            team_id=self.team.id,
            hog_flow_id=str(hog_flow.id),
            hog_flow_name="Orphan Workflow",
            created_by_id=None,
        )

        mock_create.assert_not_called()


@override_settings(INTERNAL_API_SECRET="test-secret")
class TestNotifyRateLimitedEndpoint(APIBaseTest):
    INTERNAL_URL_TEMPLATE = "/api/projects/{team_id}/internal/hog_flows/notify_rate_limited"

    def _post(self, team_id=None, data=None):
        url = self.INTERNAL_URL_TEMPLATE.format(team_id=team_id or self.team.id)
        return self.client.post(
            url,
            data=data or {},
            content_type="application/json",
            headers={"x-internal-api-secret": "test-secret"},
        )

    @patch("products.workflows.backend.services.rate_limit_notifications.handle_workflow_rate_limited")
    def test_calls_handler_with_correct_params(self, mock_handler):
        hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Workflow",
            status="active",
            created_by=self.user,
            trigger={"type": "event", "filters": {}},
            actions=[],
        )

        response = self._post(
            data={
                "hog_flow_id": str(hog_flow.id),
                "hog_flow_name": "Test Workflow",
                "created_by_id": self.user.id,
            }
        )

        assert response.status_code == 200
        mock_handler.assert_called_once_with(
            team_id=self.team.id,
            hog_flow_id=str(hog_flow.id),
            hog_flow_name="Test Workflow",
            created_by_id=self.user.id,
        )

    def test_returns_400_without_hog_flow_id(self):
        response = self._post(data={"hog_flow_name": "Test"})
        assert response.status_code == 400

    def test_rejects_unauthenticated_requests(self):
        url = self.INTERNAL_URL_TEMPLATE.format(team_id=self.team.id)
        response = self.client.post(
            url,
            data={"hog_flow_id": "abc", "hog_flow_name": "Test"},
            content_type="application/json",
        )
        assert response.status_code == 401
