import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import status

from posthog.models.dashboard import Dashboard
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.subscription import Subscription
from posthog.temporal.subscriptions.subscription_scheduling_workflow import DeliverSubscriptionReportActivityInputs

from products.enterprise.backend.api.test.base import APILicensedTest


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("products.enterprise.backend.api.subscription.sync_connect")
class TestSubscriptionTemporal(APILicensedTest):
    subscription: Subscription = None  # type: ignore
    dashboard: Dashboard = None  # type: ignore
    insight: Insight = None  # type: ignore

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(),
            team=cls.team,
            created_by=cls.user,
        )

    def _create_subscription(self, **kwargs):
        payload = {
            "insight": self.insight.id,
            "target_type": "email",
            "target_value": "test@posthog.com",
            "frequency": "weekly",
            "interval": 1,
            "start_date": "2022-01-01T00:00:00",
            "title": "My Subscription",
            "invite_message": "hey there!",
        }

        payload.update(kwargs)
        return self.client.post(f"/api/projects/{self.team.id}/subscriptions", payload)

    @pytest.mark.skip_on_multitenancy
    def test_cannot_list_subscriptions_without_proper_license(self, mock_sync, mock_feature_enabled):
        self.organization.available_product_features = []
        self.organization.save()
        response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/")
        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert response.json() == self.license_required_response()

    def test_can_create_new_subscription(self, mock_sync, mock_feature_enabled):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client
        response = self._create_subscription()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        assert data == {
            "id": data["id"],
            "dashboard": None,
            "insight": self.insight.id,
            "target_type": "email",
            "target_value": "test@posthog.com",
            "frequency": "weekly",
            "interval": 1,
            "byweekday": None,
            "bysetpos": None,
            "count": None,
            "start_date": "2022-01-01T00:00:00Z",
            "until_date": None,
            "created_at": data["created_at"],
            "created_by": data["created_by"],
            "deleted": False,
            "title": "My Subscription",
            "next_delivery_date": data["next_delivery_date"],
            "invite_message": None,
            "summary": "sent every week",
        }

        mock_client.start_workflow.assert_called_once()
        wf_args, wf_kwargs = mock_client.start_workflow.call_args
        assert wf_args[0] == "handle-subscription-value-change"
        activity_inputs = wf_args[1]
        assert isinstance(activity_inputs, DeliverSubscriptionReportActivityInputs)
        assert activity_inputs.subscription_id == data["id"]
        assert activity_inputs.invite_message == "hey there!"

    def test_can_create_new_subscription_without_invite_message(self, mock_sync, mock_feature_enabled):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client
        response = self._create_subscription(invite_message=None)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        mock_client.start_workflow.assert_called_once()

    def test_can_update_existing_subscription(self, mock_sync, mock_feature_enabled):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_sync.return_value = mock_client
        response = self._create_subscription(invite_message=None)
        data = response.json()

        mock_client.start_workflow.assert_called_once()
        mock_client.start_workflow.reset_mock()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{data['id']}",
            {
                "target_value": "test@posthog.com,new_user@posthog.com",
                "invite_message": "hi new user",
            },
        )
        updated_data = response.json()
        assert updated_data["target_value"] == "test@posthog.com,new_user@posthog.com"

        mock_client.start_workflow.assert_called_once()
        wf_args, _ = mock_client.start_workflow.call_args
        activity_inputs = wf_args[1]
        assert activity_inputs.previous_value == "test@posthog.com"
        assert activity_inputs.invite_message == "hi new user"


@patch("products.enterprise.backend.api.subscription.subscriptions")
class TestSubscription(APILicensedTest):
    subscription: Subscription = None  # type: ignore
    dashboard: Dashboard = None  # type: ignore
    insight: Insight = None  # type: ignore

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(),
            team=cls.team,
            created_by=cls.user,
        )

    def _create_subscription(self, **kwargs):
        payload = {
            "insight": self.insight.id,
            "target_type": "email",
            "target_value": "test@posthog.com",
            "frequency": "weekly",
            "interval": 1,
            "start_date": "2022-01-01T00:00:00",
            "title": "My Subscription",
            "invite_message": "hey there!",
        }

        payload.update(kwargs)
        return self.client.post(f"/api/projects/{self.team.id}/subscriptions", payload)

    @pytest.mark.skip_on_multitenancy
    def test_cannot_list_subscriptions_without_proper_license(self, mock_subscription_tasks):
        self.organization.available_product_features = []
        self.organization.save()
        response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/")
        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert response.json() == self.license_required_response()

    def test_can_create_new_subscription(self, mock_subscription_tasks):
        response = self._create_subscription()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        assert data == {
            "id": data["id"],
            "dashboard": None,
            "insight": self.insight.id,
            "target_type": "email",
            "target_value": "test@posthog.com",
            "frequency": "weekly",
            "interval": 1,
            "byweekday": None,
            "bysetpos": None,
            "count": None,
            "start_date": "2022-01-01T00:00:00Z",
            "until_date": None,
            "created_at": data["created_at"],
            "created_by": data["created_by"],
            "deleted": False,
            "title": "My Subscription",
            "next_delivery_date": data["next_delivery_date"],
            "invite_message": None,
            "summary": "sent every week",
        }

        mock_subscription_tasks.handle_subscription_value_change.delay.assert_called_once_with(
            data["id"], "", "hey there!"
        )

    def test_can_create_new_subscription_without_invite_message(self, mock_subscription_tasks):
        response = self._create_subscription(invite_message=None)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        mock_subscription_tasks.handle_subscription_value_change.delay.assert_called_once_with(data["id"], "", None)

    def test_can_update_existing_subscription(self, mock_subscription_tasks):
        response = self._create_subscription(invite_message=None)
        data = response.json()

        mock_subscription_tasks.handle_subscription_value_change.delay.assert_called_once_with(data["id"], "", None)

        mock_subscription_tasks.handle_subscription_value_change.delay.reset_mock()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{data['id']}",
            {
                "target_value": "test@posthog.com,new_user@posthog.com",
                "invite_message": "hi new user",
            },
        )
        updated_data = response.json()
        assert updated_data["target_value"] == "test@posthog.com,new_user@posthog.com"

        mock_subscription_tasks.handle_subscription_value_change.delay.assert_called_once_with(
            data["id"], "test@posthog.com", "hi new user"
        )
