import hmac
import json
import time
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.webhook_template import template

SOURCE_ID = "source_test_123"
SIGNING_KEY = "cal_signing_key_test"
SCHEMA_ID = "schema_scheduled_events"
SCHEMA_MAPPING = {"scheduled_event": SCHEMA_ID}

INVITEE_CREATED = {
    "event": "invitee.created",
    "created_at": "2026-07-02T12:00:00.000000Z",
    "created_by": "https://api.calendly.com/users/AAAA",
    "payload": {
        "uri": "https://api.calendly.com/scheduled_events/EVENT/invitees/INVITEE",
        "email": "invitee@example.com",
        "name": "Jane Doe",
        "status": "active",
        "scheduled_event": {
            "uri": "https://api.calendly.com/scheduled_events/EVENT",
            "name": "30 Minute Meeting",
            "status": "active",
            "start_time": "2026-07-10T15:00:00.000000Z",
            "end_time": "2026-07-10T15:30:00.000000Z",
            "created_at": "2026-07-02T12:00:00.000000Z",
            "updated_at": "2026-07-02T12:00:00.000000Z",
        },
    },
}


class TestCalendlyWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _signed_request(
        self,
        secret: str = SIGNING_KEY,
        body: dict | None = None,
        method: str = "POST",
        timestamp: int | None = None,
    ) -> dict:
        payload = json.dumps(body if body is not None else INVITEE_CREATED)
        ts = str(timestamp if timestamp is not None else int(time.time()))
        signature = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        return {
            "request": {
                "method": method,
                "headers": {"calendly-webhook-signature": f"t={ts},v1={signature}"},
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "signing_secret": SIGNING_KEY,
            "bypass_signature_check": False,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": SOURCE_ID,
            **overrides,
        }

    def test_valid_signed_delivery_is_routed_to_the_scheduled_events_schema(self):
        globals = self._signed_request()

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], SCHEMA_ID)

    def test_signature_signs_the_timestamp_and_body_not_the_body_alone(self):
        payload = json.dumps(INVITEE_CREATED)
        body_only = hmac.new(SIGNING_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        globals = {
            "request": {
                "method": "POST",
                "headers": {"calendly-webhook-signature": f"t={int(time.time())},v1={body_only}"},
                "body": INVITEE_CREATED,
                "stringBody": payload,
                "query": {},
            }
        }

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_signature_from_another_key_is_rejected(self):
        res = self.run_function(self._inputs(), globals=self._signed_request(secret="someone_elses_key"))

        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_replayed_delivery_outside_the_tolerance_is_rejected(self):
        globals = self._signed_request(timestamp=int(time.time()) - 400)

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": "Timestamp outside tolerance"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("null", None),
            ("empty_string", ""),
        ]
    )
    def test_unconfigured_signing_key_rejects_instead_of_accepting_anything(self, _name, signing_secret):
        res = self.run_function(
            self._inputs(signing_secret=signing_secret), globals=self._signed_request(secret="anything")
        )

        assert res.result == {"httpResponse": {"status": 400, "body": "Signing secret not configured"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("missing_header", {}, "Missing signature"),
            ("no_recognised_parts", {"calendly-webhook-signature": "nonsense"}, "Could not parse signature"),
            ("timestamp_only", {"calendly-webhook-signature": "t=12345"}, "Could not parse signature"),
        ]
    )
    def test_malformed_signature_header_is_rejected(self, _name, headers, expected_body):
        globals = {
            "request": {
                "method": "POST",
                "headers": headers,
                "body": INVITEE_CREATED,
                "stringBody": json.dumps(INVITEE_CREATED),
                "query": {},
            }
        }

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 400, "body": expected_body}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_request_is_rejected(self):
        res = self.run_function(self._inputs(), globals=self._signed_request(method="GET"))

        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_delivery_without_a_scheduled_event_is_acked_and_dropped(self):
        # A routing form submission is signed and valid, but carries no scheduled event, so it must
        # not be written into the scheduled_events table.
        body = {
            "event": "routing_form_submission.created",
            "created_at": "2026-07-02T12:00:00.000000Z",
            "payload": {"uri": "https://api.calendly.com/routing_form_submissions/SUB", "routing_form": "form"},
        }

        res = self.run_function(self._inputs(), globals=self._signed_request(body=body))

        assert res.result == {"httpResponse": {"status": 200, "body": "No scheduled event found, skipping"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_delivery_is_dropped_when_scheduled_events_is_not_synced(self):
        res = self.run_function(self._inputs(schema_mapping={}), globals=self._signed_request())

        assert res.result == {
            "httpResponse": {"status": 200, "body": "No schema mapping for scheduled events, skipping"}
        }
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
