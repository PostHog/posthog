import json
import base64
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import MAILJET_WEBHOOK_EVENTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.webhook_template import template

SOURCE_ID = "source_test_123"
AUTHORIZATION_HEADER = "Basic " + base64.b64encode(b"posthog:s3cr3t").decode()
SCHEMA_MAPPING = {"messageevent": "schema_message_events"}


class TestMailjetWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _event(self, event_type: str = "open") -> dict:
        return {
            "event": event_type,
            "time": 1433103519,
            "MessageID": 19421777396190490,
            "Message_GUID": "1ab23cd4-e567-8901-2345-6789f0gh1i2j",
            "email": "api@mailjet.com",
            "mj_campaign_id": 7173,
            "mj_contact_id": 320,
            "customcampaign": "",
        }

    def _request(self, body: dict, *, header: str | None = AUTHORIZATION_HEADER, method: str = "POST") -> dict:
        payload = json.dumps(body)
        return {
            "request": {
                "method": method,
                "headers": {} if header is None else {"authorization": header},
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "authorization_header": AUTHORIZATION_HEADER,
            "bypass_authorization_check": False,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": SOURCE_ID,
            **overrides,
        }

    @parameterized.expand([(event,) for event in MAILJET_WEBHOOK_EVENTS])
    def test_every_registered_event_type_routes_to_the_message_event_table(self, event_type):
        # Every event type PostHog subscribes to in settings.py must have a route in the template,
        # or those deliveries would be acknowledged and silently dropped.
        globals = self._request(self._event(event_type))

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once()
        row, schema_id = self.mock_produce_to_warehouse_webhooks.call_args.args
        assert schema_id == "schema_message_events"
        assert row["event"] == event_type

    def test_event_id_is_the_hash_of_the_delivered_body(self):
        # Mailjet events carry no identifier, so the merge key is derived here. A retry replays the
        # same body and must land on the same row rather than duplicating it.
        globals = self._request(self._event())

        self.run_function(self._inputs(), globals=globals)

        row = self.mock_produce_to_warehouse_webhooks.call_args.args[0]
        assert row["event_id"] == hashlib.sha256(globals["request"]["stringBody"].encode()).hexdigest()

    def test_unknown_event_type_is_acknowledged_and_dropped(self):
        # A non-200 makes Mailjet retry every 30s for 24h, so an event we do not handle still 200s.
        globals = self._request(self._event("parse"))

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_event_for_a_table_the_user_did_not_enable_is_dropped(self):
        globals = self._request(self._event())

        res = self.run_function(self._inputs(schema_mapping={}), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_grouped_delivery_is_acknowledged_and_dropped(self):
        # Mailjet's Version 2 callbacks post a JSON array. PostHog registers Version 1, but a
        # hand-configured grouped callback must not be mistaken for a single event.
        globals = self._request(self._event())
        globals["request"]["body"] = [self._event(), self._event("click")]

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("wrong_credentials", "Basic " + base64.b64encode(b"posthog:wrong").decode(), {}, 401),
            ("missing_header", None, {}, 401),
            ("no_expected_header_configured", AUTHORIZATION_HEADER, {"authorization_header": ""}, 400),
        ]
    )
    def test_unauthenticated_delivery_is_rejected(self, _name, header, input_overrides, expected_status):
        globals = self._request(self._event(), header=header)

        res = self.run_function(self._inputs(**input_overrides), globals=globals)

        assert res.result["httpResponse"]["status"] == expected_status
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_request_returns_405(self):
        globals = self._request(self._event(), method="GET")

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_bypass_authorization_check_still_routes(self):
        globals = self._request(self._event(), header=None)

        self.run_function(
            self._inputs(authorization_header="", bypass_authorization_check=True),
            globals=globals,
        )

        self.mock_produce_to_warehouse_webhooks.assert_called_once()
