from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig
from products.messaging.backend.services.customerio_sync_service import sync_preferences_to_customerio
from products.messaging.backend.tests.fakes.customerio_track_api import FakeCustomerIOTrackAPI


class TestCustomerIOSyncService(BaseTest):
    def setUp(self):
        super().setUp()
        self.track_api = self.enterContext(FakeCustomerIOTrackAPI(site_id="site_abc", api_key="key_123").installed())
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
        self.cat_posthog = MessageCategory.objects.create(team=self.team, key="internal_updates", name="Internal")

    def test_syncs_customerio_topic_preferences(self):
        prefs = {
            str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value,
            str(self.cat_8.id): PreferenceStatus.OPTED_IN.value,
        }

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        self.assertEqual(
            self.track_api.attributes_for("user@test.com"),
            {
                "cio_subscription_preferences.topics.topic_7": False,
                "cio_subscription_preferences.topics.topic_8": True,
            },
        )

    def test_transactional_categories_are_not_pushed_as_topic_changes(self):
        receipts = MessageCategory.objects.create(
            team=self.team,
            key="customerio_receipts",
            name="Receipts",
            category_type=MessageCategoryType.TRANSACTIONAL,
        )
        prefs = {
            str(self.cat_8.id): PreferenceStatus.OPTED_OUT.value,
            str(receipts.id): PreferenceStatus.OPTED_OUT.value,
        }

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        self.assertEqual(
            self.track_api.attributes_for("user@test.com"), {"cio_subscription_preferences.topics.topic_8": False}
        )

    @parameterized.expand([("us", "track.customer.io"), ("eu", "track-eu.customer.io")])
    def test_syncs_to_the_integration_region_track_host(self, region, expected_host):
        self.track_integration.config = {"region": region}
        self.track_integration.save(update_fields=["config"])

        sync_preferences_to_customerio(
            self.team.id, "user@test.com", {str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value}
        )

        self.assertEqual([request.host for request in self.track_api.received], [expected_host])

    def test_does_not_sync_posthog_only_categories(self):
        prefs = {str(self.cat_posthog.id): PreferenceStatus.OPTED_OUT.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        self.assertEqual(self.track_api.received, [])

    @parameterized.expand([(PreferenceStatus.OPTED_OUT, True), (PreferenceStatus.OPTED_IN, False)])
    def test_syncs_global_unsubscribe(self, status, expected_unsubscribed):
        prefs = {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: status.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        self.assertEqual(self.track_api.attributes_for("user@test.com"), {"unsubscribed": expected_unsubscribed})

    def test_skips_global_unsubscribe_when_all_key_absent(self):
        prefs = {str(self.cat_7.id): PreferenceStatus.OPTED_IN.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        self.assertEqual(
            self.track_api.attributes_for("user@test.com"), {"cio_subscription_preferences.topics.topic_7": True}
        )

    def test_skips_when_sync_disabled(self):
        self.config.track_enabled = False
        self.config.save(update_fields=["track_enabled"])

        sync_preferences_to_customerio(
            self.team.id, "user@test.com", {str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value}
        )

        self.assertEqual(self.track_api.received, [])

    def test_skips_when_no_config(self):
        OptOutSyncConfig.objects.filter(team=self.team).delete()

        sync_preferences_to_customerio(
            self.team.id, "user@test.com", {str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value}
        )

        self.assertEqual(self.track_api.received, [])

    def test_skips_topics_not_in_preferences(self):
        prefs = {str(self.cat_7.id): PreferenceStatus.OPTED_OUT.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        self.assertEqual(
            self.track_api.attributes_for("user@test.com"), {"cio_subscription_preferences.topics.topic_7": False}
        )

    def test_syncs_global_unsubscribe_without_customerio_categories(self):
        MessageCategory.objects.filter(team=self.team, key__startswith="customerio_").delete()

        prefs = {ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT.value}

        sync_preferences_to_customerio(self.team.id, "user@test.com", prefs)

        self.assertEqual(self.track_api.attributes_for("user@test.com"), {"unsubscribed": True})
