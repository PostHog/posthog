from unittest.mock import MagicMock, patch

from django.test import TestCase

from products.messaging.backend.services.customerio_client import CustomerIOAPIError, CustomerIOTrackClient


class TestCustomerIOTrackClient(TestCase):
    def setUp(self):
        self.track_client = CustomerIOTrackClient(site_id="site_abc", api_key="key_123", region="us")

    def test_us_region_url(self):
        self.assertEqual(self.track_client.entity_url, "https://track.customer.io/api/v2/entity")

    def test_eu_region_url(self):
        client = CustomerIOTrackClient(site_id="s", api_key="k", region="eu")
        self.assertEqual(client.entity_url, "https://track-eu.customer.io/api/v2/entity")

    @patch("products.messaging.backend.services.customerio_client.requests.Session.post")
    def test_update_subscription_preferences_sends_dot_notation(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        self.track_client.update_subscription_preferences("user@example.com", {"topic_7": False, "topic_8": True})

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        self.assertEqual(payload["type"], "person")
        self.assertEqual(payload["identifiers"], {"email": "user@example.com"})
        self.assertEqual(payload["action"], "identify")
        self.assertFalse(payload["attributes"]["cio_subscription_preferences.topics.topic_7"])
        self.assertTrue(payload["attributes"]["cio_subscription_preferences.topics.topic_8"])

    @patch("products.messaging.backend.services.customerio_client.requests.Session.post")
    def test_update_subscription_preferences_noop_when_empty(self, mock_post):
        self.track_client.update_subscription_preferences("user@example.com", {})
        mock_post.assert_not_called()

    @patch("products.messaging.backend.services.customerio_client.requests.Session.post")
    def test_set_global_unsubscribe_true(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        self.track_client.set_global_unsubscribe("user@example.com", True)

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        self.assertTrue(payload["attributes"]["unsubscribed"])

    @patch("products.messaging.backend.services.customerio_client.requests.Session.post")
    def test_set_global_unsubscribe_false(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        self.track_client.set_global_unsubscribe("user@example.com", False)

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        self.assertFalse(payload["attributes"]["unsubscribed"])

    @patch("products.messaging.backend.services.customerio_client.requests.Session.post")
    def test_identify_raises_on_http_error(self, mock_post):
        import requests

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_resp)
        mock_post.return_value = mock_resp

        with self.assertRaises(CustomerIOAPIError):
            self.track_client.set_global_unsubscribe("user@example.com", True)

    def test_auth_header_is_base64(self):
        import base64

        header = self.track_client._auth_header()
        token = header["Authorization"].removeprefix("Basic ")
        decoded = base64.b64decode(token).decode()
        self.assertEqual(decoded, "site_abc:key_123")
