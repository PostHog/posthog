import hmac
import json
import hashlib

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.attentive.webhook_template import template

SOURCE_ID = "source_test_123"


class TestAttentiveWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _make_signed_request(self, secret: str, body: dict | None = None, method: str = "POST") -> dict:
        payload = json.dumps(
            body
            or {
                "type": "sms.sent",
                "timestamp": 1632945178104,
                "company": {"display_name": "Acme", "company_id": "c1"},
                "subscriber": {"phone": "+15555555555"},
            }
        )
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return {
            "request": {
                "method": method,
                "headers": {"x-attentive-hmac-sha256": signature},
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def test_valid_signed_webhook(self):
        secret = "attentive_signing_key_test"
        globals = self._make_signed_request(secret)
        self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"sms.sent": "schema_abc"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], "schema_abc")

    def test_non_post_request_returns_405(self):
        globals = self._make_signed_request("attentive_signing_key_test", method="GET")
        res = self.run_function(
            {
                "signing_secret": "attentive_signing_key_test",
                "bypass_signature_check": False,
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    def test_invalid_signature_returns_400(self):
        globals = self._make_signed_request("wrong_secret")
        res = self.run_function(
            {
                "signing_secret": "correct_secret",
                "bypass_signature_check": False,
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_missing_signature_returns_400(self):
        body = {"type": "sms.sent"}
        globals = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": body,
                "stringBody": json.dumps(body),
                "query": {},
            }
        }
        res = self.run_function(
            {
                "signing_secret": "secret",
                "bypass_signature_check": False,
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Missing signature"}}

    def test_missing_signing_secret_returns_400(self):
        globals = self._make_signed_request("secret")
        res = self.run_function(
            {
                "signing_secret": "",
                "bypass_signature_check": False,
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Signing secret not configured"}}

    def test_bypass_signature_check(self):
        body = {"type": "email.opened", "timestamp": 1632945178104}
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
            {
                "signing_secret": "",
                "bypass_signature_check": True,
                "schema_mapping": {"email.opened": "schema_email"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(body, "schema_email")

    def test_missing_event_type_returns_200_and_skips(self):
        secret = "attentive_signing_key_test"
        globals = self._make_signed_request(secret, body={"timestamp": 1632945178104})
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"sms.sent": "schema_abc"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 200, "body": "No event type found, skipping"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_unmapped_event_type_returns_200_and_skips(self):
        secret = "attentive_signing_key_test"
        globals = self._make_signed_request(secret, body={"type": "sms.subscribed"})
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"sms.sent": "schema_abc"},
                "source_id": SOURCE_ID,
            },
            globals=globals,
        )
        assert res.result == {
            "httpResponse": {"status": 200, "body": "No schema mapping for event type: sms.subscribed, skipping"}
        }
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
