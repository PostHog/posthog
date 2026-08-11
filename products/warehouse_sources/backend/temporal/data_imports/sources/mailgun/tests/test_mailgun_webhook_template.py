import hmac
import json
import time
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    WEBHOOK_EVENT_NAMES,
    WEBHOOK_RESOURCE_KEY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.webhook_template import template

SOURCE_ID = "source_test_123"
SIGNING_KEY = "mailgun_http_webhook_signing_key"
SCHEMA_ID = "schema_webhook_events"


def _event_data(event: str = "delivered") -> dict:
    return {
        "event": event,
        "id": "CPgfbmQMTCKtHW6uIWtuVe",
        "timestamp": 1699999999.123,
        "recipient": "someone@example.com",
        "message": {"headers": {"message-id": "2019@mg.example.com"}},
    }


class TestMailgunWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
    template = template

    def createHogGlobals(self, globals=None) -> dict:
        data: dict = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": {},
                "query": {},
                "stringBody": "",
                "ip": "127.0.0.1",
            },
        }
        if globals and globals.get("request"):
            data["request"].update(globals["request"])
        return data

    def _make_signed_request(
        self,
        secret: str = SIGNING_KEY,
        event_data: dict | None = None,
        method: str = "POST",
        timestamp: int | None = None,
        token: str = "a8ce0edb2dd8301dee6c2405235584e45aa91d1e9f979f3de0",
    ) -> dict:
        ts_str = str(timestamp if timestamp is not None else int(time.time()))
        signature = hmac.new(secret.encode(), f"{ts_str}{token}".encode(), hashlib.sha256).hexdigest()
        body = {
            "signature": {"timestamp": ts_str, "token": token, "signature": signature},
            "event-data": _event_data() if event_data is None else event_data,
        }
        return {
            "request": {
                "method": method,
                "headers": {},
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "signing_secret": SIGNING_KEY,
            "bypass_signature_check": False,
            "schema_mapping": {WEBHOOK_RESOURCE_KEY: SCHEMA_ID},
            "source_id": SOURCE_ID,
            **overrides,
        }

    @parameterized.expand([(name,) for name in WEBHOOK_EVENT_NAMES])
    def test_every_subscribed_event_type_reaches_the_webhook_table(self, event_name):
        globals = self._make_signed_request(event_data=_event_data(event_name))

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], SCHEMA_ID)

    def test_non_post_request_returns_405(self):
        res = self.run_function(self._inputs(), globals=self._make_signed_request(method="GET"))

        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_signature_from_a_different_key_is_rejected(self):
        globals = self._make_signed_request(secret="not_our_signing_key")

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_replayed_delivery_outside_the_time_window_is_rejected(self):
        globals = self._make_signed_request(timestamp=int(time.time()) - 400)

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Timestamp outside tolerance"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("null", None),
            ("empty_string", ""),
        ]
    )
    def test_missing_signing_secret_returns_400(self, _name, signing_secret):
        globals = self._make_signed_request()

        res = self.run_function(self._inputs(signing_secret=signing_secret), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Signing secret not configured"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("no_signature_block", {}),
            ("missing_signature", {"timestamp": "1699999999", "token": "abc"}),
            ("missing_timestamp", {"token": "abc", "signature": "deadbeef"}),
            ("missing_token", {"timestamp": "1699999999", "signature": "deadbeef"}),
        ]
    )
    def test_incomplete_signature_block_returns_400(self, _name, signature_block):
        body = {"signature": signature_block, "event-data": _event_data()}
        globals = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Missing signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_event_type_we_do_not_subscribe_to_is_skipped(self):
        globals = self._make_signed_request(event_data=_event_data("list_member_uploaded"))

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {
            "httpResponse": {"status": 200, "body": "Unhandled event type: list_member_uploaded, skipping"}
        }
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_missing_event_name_is_skipped(self):
        globals = self._make_signed_request(event_data={"id": "evt_1", "timestamp": 1699999999.0})

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 200, "body": "No event type found, skipping"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_unmapped_resource_is_skipped(self):
        globals = self._make_signed_request()

        res = self.run_function(self._inputs(schema_mapping={}), globals=globals)

        assert res.result == {
            "httpResponse": {"status": 200, "body": "No schema mapping for event type: delivered, skipping"}
        }
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
