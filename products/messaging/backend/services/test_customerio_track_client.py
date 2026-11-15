from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.services.customerio_client import CustomerIOAPIError, CustomerIOTrackClient
from products.messaging.backend.tests.fakes.customerio_track_api import FakeCustomerIOTrackAPI, TrackRequest


class TestCustomerIOTrackClient(SimpleTestCase):
    def setUp(self):
        self.track_api = self.enterContext(FakeCustomerIOTrackAPI(site_id="site_abc", api_key="key_123").installed())
        self.track_client = CustomerIOTrackClient(site_id="site_abc", api_key="key_123", region="us")

    @parameterized.expand([("us", "track.customer.io"), ("eu", "track-eu.customer.io")])
    def test_sends_to_the_workspace_region(self, region, expected_host):
        client = CustomerIOTrackClient(site_id="site_abc", api_key="key_123", region=region)

        client.set_global_unsubscribe("user@example.com", True)

        self.assertEqual([request.host for request in self.track_api.received], [expected_host])

    def test_update_subscription_preferences_sends_dot_notation(self):
        self.track_client.update_subscription_preferences("user@example.com", {"topic_7": False, "topic_8": True})

        self.assertEqual(
            self.track_api.attributes_for("user@example.com"),
            {
                "cio_subscription_preferences.topics.topic_7": False,
                "cio_subscription_preferences.topics.topic_8": True,
            },
        )

    def test_update_subscription_preferences_noop_when_empty(self):
        self.track_client.update_subscription_preferences("user@example.com", {})

        self.assertEqual(self.track_api.received, [])

    @parameterized.expand([(True,), (False,)])
    def test_set_global_unsubscribe(self, unsubscribed):
        self.track_client.set_global_unsubscribe("user@example.com", unsubscribed)

        self.assertEqual(
            self.track_api.received,
            [
                TrackRequest(
                    host="track.customer.io",
                    path="/api/v2/entity",
                    body={
                        "type": "person",
                        "identifiers": {"email": "user@example.com"},
                        "action": "identify",
                        "attributes": {"unsubscribed": unsubscribed},
                    },
                )
            ],
        )

    def test_identify_raises_when_customerio_rejects_the_credentials(self):
        client = CustomerIOTrackClient(site_id="site_abc", api_key="revoked_key", region="us")

        with self.assertRaises(CustomerIOAPIError):
            client.set_global_unsubscribe("user@example.com", True)
