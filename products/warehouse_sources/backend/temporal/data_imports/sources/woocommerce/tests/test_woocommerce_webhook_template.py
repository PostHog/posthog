import hmac
import json
import base64
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.webhook_template import template

SOURCE_ID = "source_test_123"
SIGNING_SECRET = "cQ8oXhZ0mF3jWl2pR7tYb5NvA1sKdE6g"
SCHEMA_MAPPING = {
    "product": "schema_products",
    "order": "schema_orders",
    "coupon": "schema_coupons",
    "customer": "schema_customers",
}


class TestWooCommerceWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _object(self, object_id: int = 42) -> dict:
        return {
            "id": object_id,
            "status": "completed",
            "date_created_gmt": "2026-05-01T10:00:00",
            "date_modified_gmt": "2026-05-01T11:00:00",
        }

    def _request(
        self,
        secret: str,
        body: dict,
        resource: str = "order",
        event: str = "updated",
        method: str = "POST",
    ) -> dict:
        payload = json.dumps(body)
        signature = base64.b64encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()).decode()
        return {
            "request": {
                "method": method,
                "headers": {
                    "x-wc-webhook-signature": signature,
                    "x-wc-webhook-resource": resource,
                    "x-wc-webhook-event": event,
                    "x-wc-webhook-topic": f"{resource}.{event}",
                },
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
            ("product", "created", "schema_products"),
            ("product", "updated", "schema_products"),
            ("order", "created", "schema_orders"),
            ("order", "updated", "schema_orders"),
            ("coupon", "updated", "schema_coupons"),
            ("customer", "created", "schema_customers"),
        ]
    )
    def test_routes_each_subscribed_topic_to_its_table(self, resource, event, expected_schema_id):
        # WooCommerce puts the object type in a header, not the body, and signs with base64
        # rather than hex - getting either wrong drops every delivery.
        globals = self._request(SIGNING_SECRET, self._object(), resource=resource, event=event)

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], expected_schema_id)

    def test_delete_event_is_dropped(self):
        # A `.deleted` payload is only `{"id": ...}`; merging it would null every other column
        # on the row it matched.
        globals = self._request(SIGNING_SECRET, {"id": 42}, resource="order", event="deleted")

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("unmapped_resource", {"x-wc-webhook-resource": "product_review"}, SCHEMA_MAPPING),
            ("table_not_enabled", {}, {"product": "schema_products"}),
        ]
    )
    def test_delivery_with_no_schema_is_acknowledged_and_dropped(self, _name, header_overrides, schema_mapping):
        # WooCommerce disables a webhook after five consecutive non-2xx responses, so a delivery
        # we have nowhere to put must still be acknowledged.
        globals = self._request(SIGNING_SECRET, self._object())
        globals["request"]["headers"].update(header_overrides)

        res = self.run_function(self._inputs(schema_mapping=schema_mapping), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_payload_without_an_id_is_dropped(self):
        globals = self._request(SIGNING_SECRET, {"status": "completed"})

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_bad_signature_is_rejected(self):
        globals = self._request("some-other-secret", self._object())

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("missing_signature", {}, {"signing_secret": SIGNING_SECRET}, "Missing signature"),
            (
                "no_secret_configured",
                {"x-wc-webhook-signature": "x"},
                {"signing_secret": ""},
                "Signing secret not configured",
            ),
        ]
    )
    def test_unverifiable_delivery_is_rejected(self, _name, headers, input_overrides, expected_body):
        body = self._object()
        globals = {
            "request": {
                "method": "POST",
                "headers": {"x-wc-webhook-resource": "order", "x-wc-webhook-event": "updated", **headers},
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }

        res = self.run_function(self._inputs(**input_overrides), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": expected_body}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_request_returns_405(self):
        globals = self._request(SIGNING_SECRET, self._object(), method="GET")

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_bypass_signature_check_still_routes(self):
        body = self._object()
        globals = {
            "request": {
                "method": "POST",
                "headers": {"x-wc-webhook-resource": "order", "x-wc-webhook-event": "updated"},
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }

        self.run_function(self._inputs(signing_secret="", bypass_signature_check=True), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(body, "schema_orders")
