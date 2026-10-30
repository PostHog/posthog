import hmac
import json
import time
import base64
import hashlib

from parameterized import parameterized

from products.cdp.backend.templates.helpers import BaseHogFunctionTemplateSimpleTest
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import WEBHOOK_EVENT_TO_SCHEMA
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.webhook_template import template

# Svix secrets are random bytes. These are not valid UTF-8, so a template that uses the secret as a
# string key fails to verify.
KEY_BYTES = bytes(range(0xE0, 0xF8))
SECRET = "whsec_" + base64.b64encode(KEY_BYTES).decode()


class TestClerkWarehouseWebhookTemplate(BaseHogFunctionTemplateSimpleTest):
    template = template

    def createHogGlobals(self, globals=None) -> dict:
        data = {"request": {"method": "POST", "headers": {}, "body": {}, "query": {}, "stringBody": ""}}
        if globals and globals.get("request"):
            data["request"].update(globals["request"])
        return data

    def _request(
        self, body: dict, key: bytes = KEY_BYTES, timestamp: int | None = None, extra_signature: str = ""
    ) -> dict:
        payload = json.dumps(body)
        message_id = "msg_test"
        timestamp_string = str(timestamp if timestamp is not None else int(time.time()))
        digest = hmac.new(key, f"{message_id}.{timestamp_string}.{payload}".encode(), hashlib.sha256).digest()
        signature = f"{extra_signature}v1,{base64.b64encode(digest).decode()}"
        return {
            "request": {
                "method": "POST",
                "headers": {"svix-id": message_id, "svix-timestamp": timestamp_string, "svix-signature": signature},
                "body": body,
                "query": {},
                "stringBody": payload,
            }
        }

    def _run(self, globals: dict, schema_mapping: dict | None = None):
        return self.run_function(
            {"signing_secret": SECRET, "bypass_signature_check": False, "schema_mapping": schema_mapping or {}},
            globals=globals,
        )

    @parameterized.expand(sorted(WEBHOOK_EVENT_TO_SCHEMA.items()))
    def test_routes_supported_events(self, event_type: str, resource: str) -> None:
        body = {"type": event_type, "object": "event", "data": {"id": "resource_1"}}
        self._run(self._request(body), {resource: "schema_1"})
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(body, "schema_1")

    def test_accepts_any_matching_signature_in_the_header(self) -> None:
        # Svix lists one signature per active secret while a secret rotates.
        body = {"type": "user.created", "data": {"id": "user_1"}}
        self._run(self._request(body, extra_signature="v1,c3RhbGU= "), {"users": "schema_1"})
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(body, "schema_1")

    @parameterized.expand(
        [
            ("delete_event", "user.deleted", {"users": "schema_1"}, "Unhandled event type"),
            ("unhandled_event", "email.created", {"users": "schema_1"}, "Unhandled event type"),
            ("unmapped_resource", "user.created", {}, "No schema mapping"),
        ]
    )
    def test_acknowledges_events_it_does_not_store(
        self, _label: str, event_type: str, schema_mapping: dict, expected_body: str
    ) -> None:
        # A non-200 makes Svix retry, then disable the endpoint, for events PostHog never stores.
        result = self._run(self._request({"type": event_type, "data": {"id": "user_1"}}), schema_mapping)

        assert result.result["httpResponse"]["status"] == 200
        assert expected_body in result.result["httpResponse"]["body"]
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("wrong_key", {"key": bytes(range(24))}, "Bad signature"),
            ("stale", {"timestamp": int(time.time()) - 301}, "Timestamp outside tolerance"),
        ]
    )
    def test_rejects_unverified_delivery(self, _label: str, request_kwargs: dict, expected_body: str) -> None:
        body = {"type": "user.created", "data": {"id": "user_1"}}
        result = self._run(self._request(body, **request_kwargs), {"users": "schema_1"})

        assert result.result == {"httpResponse": {"status": 400, "body": expected_body}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_rejects_delivery_without_svix_headers(self) -> None:
        body = {"type": "user.created", "data": {"id": "user_1"}}
        result = self._run(
            {"request": {"method": "POST", "headers": {}, "body": body, "stringBody": json.dumps(body)}},
            {"users": "schema_1"},
        )

        assert result.result == {"httpResponse": {"status": 400, "body": "Missing signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
