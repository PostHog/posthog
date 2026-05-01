from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig
from products.messaging.backend.services.customerio_sync_service import sync_preferences_to_customerio


class TestCustomerIOSyncService(BaseTest):
    def setUp(self):
        super().setUp()
        self.track_integration = Integration.objects.create(
            team=self.team,
            kind="customerio-track",
            sensitive_config={"site_id": "site_abc", "api_key": "key_123"},
            config={"region": "us"},
            created_by=self.user,
        )
        self.config = OptOutSyncConfig.objects.create(
            team=self.team,
            track_integration=self.track_integration,
            track_enabled=True,
        )
        self.cat_7 = MessageCategory.objects.create(team=self.team, key="customerio_topic_7", name="Product updates")
        self.cat_8 = MessageCategory.objects.create(team=self.team, key="customerio_topic_8", name="Newsletter")
        # A PostHog-only category — should NOT be synced
        self.cat_posthog = MessageCategory.objects.create(team=self.team, key="internal_updates", name="Internal")

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_syncs_customerio_topic_preferences(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        prefs = {
            str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value,
            str(self.cat_8.id): PreferenceStatus.OPTED_IN.value,
        }

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        mock_client.update_subscription_preferences.assert_called_once_with(
            "user@test.com", {"topic_7": False, "topic_8": True}
        )

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_does_not_sync_posthog_only_categories(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        prefs = {str(self.cat_posthog.id): PreferenceStatus.OPTED_OUT.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        # No customerio_* categories in prefs, so no topic call
        mock_client.update_subscription_preferences.assert_not_called()

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_syncs_global_unsubscribe(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        prefs = {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        mock_client.set_global_unsubscribe.assert_called_once_with("user@test.com", True)

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_skips_global_unsubscribe_when_all_key_absent(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        prefs = {str(self.cat_7.id): PreferenceStatus.OPTED_IN.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        mock_client.set_global_unsubscribe.assert_not_called()

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_skips_when_sync_disabled(self, mock_client_class):
        self.config.track_enabled = False
        self.config.save(update_fields=["track_enabled"])

        sync_preferences_to_customerio(
            self.team.id, "user@test.com", {str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value}
        )

        mock_client_class.assert_not_called()

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_skips_when_no_config(self, mock_client_class):
        OptOutSyncConfig.objects.filter(team=self.team).delete()

        sync_preferences_to_customerio(self.team.id, "user@test.com", {"some": "pref"})

        mock_client_class.assert_not_called()

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_skips_topics_not_in_preferences(self, mock_client_class):
        """Categories that exist but aren't in the preferences dict are skipped."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Only cat_7 in prefs, cat_8 absent
        prefs = {str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        mock_client.update_subscription_preferences.assert_called_once_with("user@test.com", {"topic_7": False})

    @patch("products.messaging.backend.services.customerio_sync_service.CustomerIOTrackClient")
    def test_syncs_global_unsubscribe_without_customerio_categories(self, mock_client_class):
        """Global unsub must still sync when no customerio_* categories exist."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Team has only PostHog-native categories, no customerio_* ones
        MessageCategory.objects.filter(team=self.team, key__startswith="customerio_").delete()

        prefs = {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        mock_client.set_global_unsubscribe.assert_called_once_with("user@test.com", True)
        mock_client.update_subscription_preferences.assert_not_called()
