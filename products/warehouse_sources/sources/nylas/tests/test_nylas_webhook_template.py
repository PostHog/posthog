import hmac
import json
import hashlib

from parameterized import parameterized

from products.warehouse_sources.sources.nylas.webhook_template import template
from products.warehouse_sources.sources.sdk.testing import BaseHogFunctionTemplateSimpleTest

WEBHOOK_SECRET = "nylas-webhook-secret-for-tests"
SCHEMA_MAPPING = {"message": "schema_messages", "event": "schema_events", "contact": "schema_contacts"}


def _notification(event_type: str = "message.created", object_type: str = "message") -> dict:
    return {
        "specversion": "1.0",
        "type": event_type,
        "source": "/google/emails/realtime",
        "id": "evt-1",
        "time": 1723821985,
        "data": {
            "application_id": "app-1",
            "object": {"object": object_type, "id": "msg-1", "grant_id": "grant-1", "subject": "Hello"},
        },
    }


class TestNylasWarehouseWebhookTemplate(BaseHogFunctionTemplateSimpleTest):
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

    def _post(self, body: dict, signature: str | None = None, secret: str = WEBHOOK_SECRET) -> dict:
        payload = json.dumps(body)
        if signature is None:
            signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return {
            "request": {
                "method": "POST",
                "headers": {"x-nylas-signature": signature} if signature else {},
                "body": body,
                "stringBody": payload,
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "signing_secret": WEBHOOK_SECRET,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": "source-1",
            **overrides,
        }

    @parameterized.expand([("with_secret", WEBHOOK_SECRET), ("before_the_secret_is_stored", "")])
    def test_challenge_request_echoes_the_bare_value(self, _name, secret):
        # Nylas sends the challenge while the create call is still open, so the secret is not
        # stored yet. A failed challenge makes Nylas reject the webhook with no retry.
        globals = {"request": {"method": "GET", "query": {"challenge": "bc609b38-c81f-47fb-a275-1d9bd61a968b"}}}

        res = self.run_function(self._inputs(signing_secret=secret), globals=globals)

        assert res.result["httpResponse"] == {
            "status": 200,
            "contentType": "text/plain",
            "body": "bc609b38-c81f-47fb-a275-1d9bd61a968b",
        }
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand([("missing", {}), ("markup", {"challenge": "<script>alert(1)</script>"})])
    def test_challenge_request_rejects_values_that_are_not_a_plain_token(self, _name, query):
        res = self.run_function(self._inputs(), globals={"request": {"method": "GET", "query": query}})

        assert res.result["httpResponse"]["status"] == 400
        assert "script" not in res.result["httpResponse"]["body"]

    @parameterized.expand(
        [
            ("message.created",),
            ("message.updated",),
            ("message.created.truncated",),
            ("message.updated.transformed",),
        ]
    )
    def test_signed_message_notifications_go_to_the_messages_table(self, event_type):
        globals = self._post(_notification(event_type))

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], "schema_messages")

    @parameterized.expand(
        [
            ("event.created", "event", "schema_events"),
            ("event.deleted", "event", "schema_events"),
            ("contact.updated", "contact", "schema_contacts"),
        ]
    )
    def test_event_and_contact_notifications_go_to_their_own_table(self, event_type, object_type, schema_id):
        globals = self._post(_notification(event_type, object_type))

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], schema_id)

    def test_uppercase_hex_signature_is_accepted(self):
        body = _notification()
        signature = hmac.new(WEBHOOK_SECRET.encode(), json.dumps(body).encode(), hashlib.sha256).hexdigest().upper()

        self.run_function(self._inputs(), globals=self._post(body, signature=signature))

        self.mock_produce_to_warehouse_webhooks.assert_called_once()

    @parameterized.expand(
        [
            ("wrong_secret", {"secret": "another-secret"}),
            ("missing_header", {"signature": ""}),
        ]
    )
    def test_unsigned_or_wrongly_signed_notifications_are_rejected(self, _name, kwargs):
        res = self.run_function(self._inputs(), globals=self._post(_notification(), **kwargs))

        assert res.result["httpResponse"]["status"] == 400
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_notifications_are_dropped_until_the_secret_is_stored(self):
        res = self.run_function(self._inputs(signing_secret=""), globals=self._post(_notification()))

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand([("grant.expired",), ("message.opened",), ("thread.replied",), ("contact.deleted",)])
    def test_other_signed_notifications_are_acknowledged_and_dropped(self, event_type):
        # A manually broadened webhook must get a 200, or Nylas marks the webhook as failing.
        res = self.run_function(self._inputs(), globals=self._post(_notification(event_type)))

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_message_notification_is_dropped_when_the_table_is_not_enabled(self):
        res = self.run_function(self._inputs(schema_mapping={}), globals=self._post(_notification()))

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
