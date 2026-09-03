import hmac
import json
import time
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import WEBHOOK_EVENT_TO_SCHEMA
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.webhook_template import template


class TestWorkOSWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
    template = template

    def createHogGlobals(self, globals=None) -> dict:
        data = {"request": {"method": "POST", "headers": {}, "body": {}, "query": {}, "stringBody": ""}}
        if globals and globals.get("request"):
            data["request"].update(globals["request"])
        return data

    def _request(self, secret: str, body: dict, timestamp: int | None = None) -> dict:
        payload = json.dumps(body)
        timestamp_string = str(timestamp if timestamp is not None else int(time.time() * 1000))
        signature = hmac.new(secret.encode(), f"{timestamp_string}.{payload}".encode(), hashlib.sha256).hexdigest()
        return {
            "request": {
                "method": "POST",
                "headers": {"workos-signature": f"t={timestamp_string},v1={signature}"},
                "body": body,
                "query": {},
                "stringBody": payload,
            }
        }

    @parameterized.expand(sorted(WEBHOOK_EVENT_TO_SCHEMA.items()))
    def test_routes_supported_events(self, event_type: str, resource: str) -> None:
        body = {"id": "event_1", "event": event_type, "data": {"id": "resource_1"}}
        globals = self._request("secret", body)
        self.run_function(
            {
                "signing_secret": "secret",
                "bypass_signature_check": False,
                "schema_mapping": {resource: "schema_1"},
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(body, "schema_1")

    @parameterized.expand(
        [
            ("unhandled_event", "invoice.created", {"users": "schema_1"}, "Unhandled event type"),
            ("unmapped_resource", "user.created", {}, "No schema mapping"),
        ]
    )
    def test_acknowledges_events_it_does_not_store(
        self, _label: str, event_type: str, schema_mapping: dict, expected_body: str
    ) -> None:
        # A non-200 here makes WorkOS retry, then disable the endpoint, for events the user
        # never asked to sync.
        globals = self._request("secret", {"event": event_type, "data": {"id": "resource_1"}})
        result = self.run_function(
            {"signing_secret": "secret", "bypass_signature_check": False, "schema_mapping": schema_mapping},
            globals=globals,
        )

        assert result.result["httpResponse"]["status"] == 200
        assert expected_body in result.result["httpResponse"]["body"]
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_rejects_delivery_without_a_signature_header(self) -> None:
        body = {"event": "user.created", "data": {"id": "user_1"}}
        result = self.run_function(
            {"signing_secret": "secret", "bypass_signature_check": False, "schema_mapping": {"users": "schema_1"}},
            globals={"request": {"method": "POST", "headers": {}, "body": body, "stringBody": json.dumps(body)}},
        )

        assert result.result == {"httpResponse": {"status": 400, "body": "Missing signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_rejects_invalid_signature(self) -> None:
        globals = self._request("wrong", {"event": "user.created", "data": {"id": "user_1"}})
        result = self.run_function(
            {"signing_secret": "correct", "bypass_signature_check": False, "schema_mapping": {}}, globals=globals
        )
        assert result.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}

    def test_rejects_stale_signature(self) -> None:
        globals = self._request(
            "secret", {"event": "user.created", "data": {"id": "user_1"}}, int(time.time() * 1000) - 180001
        )
        result = self.run_function(
            {"signing_secret": "secret", "bypass_signature_check": False, "schema_mapping": {}}, globals=globals
        )
        assert result.result == {"httpResponse": {"status": 400, "body": "Timestamp outside tolerance"}}
