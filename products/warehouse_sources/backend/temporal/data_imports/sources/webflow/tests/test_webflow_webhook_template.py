import hmac
import json
import time
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webhook_template import template

SOURCE_ID = "source_test_123"
NEW_ORDER_SECRET = "2b4acfd1c5518bf03c73a4889d197d77251353857c22694bf150b9e3402ba15f"
ORDER_CHANGED_SECRET = "9f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
SCHEMA_MAPPING = {"orders": "schema_orders"}


def _now_ms() -> int:
    return int(time.time() * 1000)


class TestWebflowWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _event(self, trigger_type: str = "ecomm_new_order") -> dict:
        return {
            "triggerType": trigger_type,
            "payload": {
                "orderId": "abc123",
                "status": "unfulfilled",
                "acceptedOn": "2026-05-01T10:00:00.000Z",
            },
        }

    def _request(self, secret: str, body: dict, method: str = "POST", timestamp: int | None = None) -> dict:
        payload = json.dumps(body)
        request_timestamp = _now_ms() if timestamp is None else timestamp
        signature = hmac.new(secret.encode(), f"{request_timestamp}:{payload}".encode(), hashlib.sha256).hexdigest()
        return {
            "request": {
                "method": method,
                "headers": {
                    "x-webflow-signature": signature,
                    "x-webflow-timestamp": str(request_timestamp),
                },
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "signing_secret": "",
            "signing_secrets": [NEW_ORDER_SECRET, ORDER_CHANGED_SECRET],
            "bypass_signature_check": False,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": SOURCE_ID,
            **overrides,
        }

    @parameterized.expand(
        [
            ("new_order", "ecomm_new_order", NEW_ORDER_SECRET),
            ("order_changed", "ecomm_order_changed", ORDER_CHANGED_SECRET),
        ]
    )
    def test_each_order_trigger_verifies_against_its_own_secret_and_routes_to_orders(
        self, _name: str, trigger_type: str, secret: str
    ) -> None:
        # Webflow issues a separate secret per trigger registration, so a template that only
        # checked one of them would reject half the deliveries.
        globals = self._request(secret, self._event(trigger_type))

        self.run_function(self._inputs(), globals=globals)

        produced, schema_id = self.mock_produce_to_warehouse_webhooks.call_args.args
        assert schema_id == "schema_orders"
        assert produced["triggerType"] == trigger_type
        # The Order object is delivered unwrapped so pushed rows match the polled table.
        assert produced["payload"]["orderId"] == "abc123"
        assert produced["webflowTimestamp"] == globals["request"]["headers"]["x-webflow-timestamp"]

    def test_manually_entered_secret_is_accepted(self) -> None:
        # Sites set up by hand have no secrets from the create response, only the one pasted in.
        globals = self._request("pasted-by-hand", self._event())

        self.run_function(
            self._inputs(signing_secret="pasted-by-hand", signing_secrets=[]),
            globals=globals,
        )

        self.mock_produce_to_warehouse_webhooks.assert_called_once()

    def test_bad_signature_is_rejected(self) -> None:
        globals = self._request("some-other-secret", self._event())

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_replayed_delivery_is_rejected(self) -> None:
        # The signature covers the timestamp, so without an age check a captured delivery would
        # stay valid forever and could rewrite an order row.
        globals = self._request(NEW_ORDER_SECRET, self._event(), timestamp=_now_ms() - 600_000)

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Stale delivery"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("missing_signature", {"x-webflow-timestamp": "1700000000000"}, {}, "Missing signature"),
            ("missing_timestamp", {"x-webflow-signature": "abc"}, {}, "Missing signature"),
            (
                "no_secret_configured",
                {"x-webflow-signature": "abc", "x-webflow-timestamp": "1700000000000"},
                {"signing_secret": "", "signing_secrets": []},
                "Signing secret not configured",
            ),
        ]
    )
    def test_unverifiable_delivery_is_rejected(
        self, _name: str, headers: dict, input_overrides: dict, expected_body: str
    ) -> None:
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

    def test_unhandled_trigger_is_acknowledged_and_dropped(self) -> None:
        # A site can carry webhooks we didn't register; a 500 here would put Webflow into a
        # retry loop and eventually deactivate our webhook.
        globals = self._request(NEW_ORDER_SECRET, {"triggerType": "site_publish", "payload": {"siteId": "s1"}})

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_event_for_a_table_the_user_did_not_enable_is_dropped(self) -> None:
        globals = self._request(NEW_ORDER_SECRET, self._event())

        res = self.run_function(self._inputs(schema_mapping={}), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_request_returns_405(self) -> None:
        globals = self._request(NEW_ORDER_SECRET, self._event(), method="GET")

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_bypass_signature_check_still_routes(self) -> None:
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

        self.run_function(
            self._inputs(signing_secret="", signing_secrets=[], bypass_signature_check=True), globals=globals
        )

        self.mock_produce_to_warehouse_webhooks.assert_called_once()
