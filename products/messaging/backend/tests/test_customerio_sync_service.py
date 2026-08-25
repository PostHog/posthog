from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import PreferenceStatus
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig
from products.messaging.backend.services.customerio_sync_service import sync_preferences_to_customerio


class TestCustomerIOSyncService(BaseTest):
    def setUp(self):
        super().setUp()
        integration = Integration.objects.create(
            team=self.team,
            kind="customerio-track",
            config={"region": "us"},
            sensitive_config={"site_id": "site", "api_key": "key"},
            created_by=self.user,
        )
        OptOutSyncConfig.objects.create(team=self.team, track_integration=integration, track_enabled=True)

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_transactional_categories_are_not_pushed_as_topic_changes(self, mock_client_cls):
        # Transactional sends bypass opt-outs, so a stored preference on a transactional
        # category must not reach Customer.io, where it would unsubscribe the recipient from
        # a real topic.
        marketing = MessageCategory.objects.create(team=self.team, key="customerio_newsletter", name="Newsletter")
        transactional = MessageCategory.objects.create(
            team=self.team,
            key="customerio_receipts",
            name="Receipts",
            category_type=MessageCategoryType.TRANSACTIONAL,
        )

        sync_preferences_to_customerio(
            self.team.id,
            "user@example.com",
            {
                str(marketing.id): PreferenceStatus.OPTED_OUT.value,
                str(transactional.id): PreferenceStatus.OPTED_OUT.value,
            },
        )

        mock_client_cls.return_value.update_subscription_preferences.assert_called_once_with(
            "user@example.com", {"newsletter": False}
        )
