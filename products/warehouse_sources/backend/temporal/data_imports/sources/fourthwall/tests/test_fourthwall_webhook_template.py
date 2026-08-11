import hmac
import json
import base64
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.webhook_template import template

SOURCE_ID = "source_test_123"
SIGNING_SECRET = "e3f93c7c-c92b-4b8f-a9b1-5b70e0891abc"
SCHEMA_MAPPING = {"order": "schema_orders", "donation": "schema_donations", "member": "schema_members"}


class TestFourthwallWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _event(self, event_type: str = "ORDER_PLACED") -> dict:
        return {
            "id": "weve_1",
            "webhookId": "wcon_1",
            "shopId": "sh_1",
            "type": event_type,
            "apiVersion": "V1",
            "createdAt": "2026-05-01T10:00:00+00:00",
            "testMode": False,
            "data": {"id": "order_1", "status": "CONFIRMED"},
        }

    def _request(self, secret: str, body: dict, method: str = "POST") -> dict:
        payload = json.dumps(body)
        signature = base64.b64encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()).decode()
        return {
            "request": {
                "method": method,
                "headers": {"x-fourthwall-hmac-sha256": signature},
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "signing_secret": SIGNING_SECRET,
            "bypass_signature_check": False,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": SOURCE_ID,
            **overrides,
        }

    @parameterized.expand(
        [
            ("ORDER_PLACED", "schema_orders"),
            ("ORDER_UPDATED", "schema_orders"),
            ("DONATION", "schema_donations"),
            ("SUBSCRIPTION_PURCHASED", "schema_members"),
            ("SUBSCRIPTION_CHANGED", "schema_members"),
            ("SUBSCRIPTION_EXPIRED", "schema_members"),
        ]
    )
    def test_routes_each_subscribed_event_to_its_table(self, event_type, expected_schema_id):
        # Fourthwall signs with base64, not hex; a hex comparison would reject every delivery.
        globals = self._request(SIGNING_SECRET, self._event(event_type))

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], expected_schema_id)

    def test_unsubscribed_event_is_acknowledged_and_dropped(self):
        # Fourthwall delivers every event the webhook is subscribed to; an unmapped one must
        # not 500 the endpoint into a retry storm.
        globals = self._request(SIGNING_SECRET, self._event("THANK_YOU_SENT"))

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_event_for_a_table_the_user_did_not_enable_is_dropped(self):
        globals = self._request(SIGNING_SECRET, self._event("DONATION"))

        res = self.run_function(self._inputs(schema_mapping={"order": "schema_orders"}), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_bad_signature_is_rejected(self):
        globals = self._request("some-other-secret", self._event())

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("missing_signature", {}, {"signing_secret": SIGNING_SECRET}, "Missing signature"),
            (
                "no_secret_configured",
                {"x-fourthwall-hmac-sha256": "x"},
                {"signing_secret": ""},
                "Signing secret not configured",
            ),
        ]
    )
    def test_unverifiable_delivery_is_rejected(self, _name, headers, input_overrides, expected_body):
        body = self._event()
        globals = {
            "request": {
                "method": "POST",
                "headers": headers,
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }

        res = self.run_function(self._inputs(**input_overrides), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": expected_body}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_request_returns_405(self):
        globals = self._request(SIGNING_SECRET, self._event(), method="GET")

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_bypass_signature_check_still_routes(self):
        body = self._event()
        globals = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }

        self.run_function(self._inputs(signing_secret="", bypass_signature_check=True), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(body, "schema_orders")
