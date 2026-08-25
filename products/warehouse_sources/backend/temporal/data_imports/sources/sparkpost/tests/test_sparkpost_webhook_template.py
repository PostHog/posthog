import json
import base64

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import WEBHOOK_BATCH_KEY
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.webhook_template import template

SOURCE_ID = "source_test_123"
AUTH_HEADER = "Basic " + base64.b64encode(b"posthog:s3cr3t").decode()
SCHEMA_MAPPING = {"message_event": "schema_events"}


class TestSparkPostWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
    template = template

    def createHogGlobals(self, globals=None) -> dict:
        data: dict = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": [],
                "query": {},
                "stringBody": "",
                "ip": "127.0.0.1",
            },
        }
        if globals and globals.get("request"):
            data["request"].update(globals["request"])
        return data

    def _batch(self, *events) -> list:
        return [{"msys": {"message_event": event}} for event in events] or [
            {"msys": {"message_event": {"event_id": "1", "type": "delivery", "timestamp": "1460989507"}}}
        ]

    def _request(self, body, header=AUTH_HEADER, method: str = "POST") -> dict:
        payload = json.dumps(body)
        return {
            "request": {
                "method": method,
                "headers": {"authorization": header} if header is not None else {},
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "authorization_header": AUTH_HEADER,
            "bypass_authorization_check": False,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": SOURCE_ID,
            **overrides,
        }

    def test_authenticated_batch_is_handed_over_whole(self):
        # SparkPost POSTs a batch per delivery but only one payload may be produced per request, so
        # the entire batch has to survive the handover for the source transformer to explode.
        body = self._batch(
            {"event_id": "1", "type": "delivery", "timestamp": "1460989507"},
            {"event_id": "2", "type": "open", "timestamp": "1460989600"},
        )

        self.run_function(self._inputs(), globals=self._request(body))

        payload, schema_id = self.mock_produce_to_warehouse_webhooks.call_args[0]
        assert schema_id == "schema_events"
        assert json.loads(payload[WEBHOOK_BATCH_KEY]) == body

    @parameterized.expand(
        [
            ("wrong_credentials", "Basic " + base64.b64encode(b"posthog:guessed").decode(), 401),
            ("empty_header", "", 401),
            ("no_header_at_all", None, 401),
        ]
    )
    def test_unauthenticated_delivery_is_rejected(self, _name, header, expected_status):
        # SparkPost signs nothing, so this header comparison is the only thing standing between the
        # ingest endpoint and anyone who guesses its URL.
        res = self.run_function(self._inputs(), globals=self._request(self._batch(), header=header))

        assert res.result["httpResponse"]["status"] == expected_status
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_delivery_is_rejected_when_no_credentials_are_configured(self):
        res = self.run_function(
            self._inputs(authorization_header=""), globals=self._request(self._batch(), header="Basic anything")
        )

        assert res.result == {"httpResponse": {"status": 400, "body": "Authorization header value not configured"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_events_table_not_enabled_is_acknowledged_and_dropped(self):
        # SparkPost retries on a non-2xx, so an unmapped delivery must be acknowledged rather than
        # turned into a retry storm.
        res = self.run_function(self._inputs(schema_mapping={}), globals=self._request(self._batch()))

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_empty_batch_is_acknowledged_without_producing(self):
        res = self.run_function(self._inputs(), globals=self._request([]))

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_request_returns_405(self):
        res = self.run_function(self._inputs(), globals=self._request(self._batch(), method="GET"))

        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_bypass_authorization_check_still_routes(self):
        body = self._batch()

        self.run_function(
            self._inputs(authorization_header="", bypass_authorization_check=True),
            globals=self._request(body, header=None),
        )

        payload, schema_id = self.mock_produce_to_warehouse_webhooks.call_args[0]
        assert schema_id == "schema_events"
        assert json.loads(payload[WEBHOOK_BATCH_KEY]) == body
