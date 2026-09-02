import json

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import WEBHOOK_SECRET_HEADER
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.webhook_template import template

SOURCE_ID = "source_test_123"
WEBHOOK_SECRET = "0Pm2Yb8bJ0Yl7vGQ9m1Z2xTn5cRk4dWq"
SCHEMA_MAPPING = {"Bounce": "schema_bounces"}


class TestPostmarkWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _bounce(self, record_type: str = "Bounce") -> dict:
        return {
            "RecordType": record_type,
            "MessageStream": "outbound",
            "ID": 4323372036854775807,
            "Type": "HardBounce",
            "TypeCode": 1,
            "Email": "john@example.com",
            "BouncedAt": "2026-01-05T16:33:54.9070259Z",
        }

    def _request(self, body: dict, headers: dict | None = None, method: str = "POST") -> dict:
        payload = json.dumps(body)
        return {
            "request": {
                "method": method,
                "headers": {WEBHOOK_SECRET_HEADER: WEBHOOK_SECRET} if headers is None else headers,
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "signing_secret": WEBHOOK_SECRET,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": SOURCE_ID,
            **overrides,
        }

    @parameterized.expand([("Bounce",), ("SpamComplaint",)])
    def test_routes_bounce_records_to_the_bounces_table(self, record_type):
        # Spam complaints are bounce records too, and the Bounce API lists them alongside the
        # rest — routing them elsewhere (or dropping them) would lose rows once webhooks take
        # over from polling.
        globals = self._request(self._bounce(record_type))

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], "schema_bounces")

    @parameterized.expand([("Delivery",), ("Open",), ("SubscriptionChange",)])
    def test_other_record_types_are_acknowledged_and_dropped(self, record_type):
        # A manually broadened webhook can deliver triggers we have no table for; a 5xx here
        # would put Postmark into a retry storm.
        globals = self._request(self._bounce(record_type))

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_bounce_is_dropped_when_the_table_is_not_enabled(self):
        globals = self._request(self._bounce())

        res = self.run_function(self._inputs(schema_mapping={}), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("wrong_secret", {WEBHOOK_SECRET_HEADER: "not-the-secret"}, {}, "Bad webhook secret"),
            ("missing_header", {}, {}, "Bad webhook secret"),
            (
                "secret_not_configured",
                {WEBHOOK_SECRET_HEADER: WEBHOOK_SECRET},
                {"signing_secret": ""},
                "Webhook secret not configured",
            ),
        ]
    )
    def test_unauthenticated_deliveries_are_rejected(self, _name, headers, input_overrides, expected_body):
        # Postmark signs nothing, so this header is the only proof of origin. There is no bypass
        # input, so no configuration can accept an unauthenticated delivery.
        globals = self._request(self._bounce(), headers=headers)

        res = self.run_function(self._inputs(**input_overrides), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": expected_body}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_is_rejected(self):
        globals = self._request(self._bounce(), method="GET")

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 405
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
