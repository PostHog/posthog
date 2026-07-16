import hmac
import json
import time
import hashlib

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.webhook_template import template

TRANSACTION_PAYLOAD = json.dumps(
    {
        "event_type": "transaction.completed",
        "data": {"id": "txn_01", "status": "completed"},
    }
)


class TestPaddleWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _sign(self, payload: str, secret: str, timestamp: str = "1671552777") -> str:
        return hmac.new(secret.encode(), f"{timestamp}:{payload}".encode(), hashlib.sha256).hexdigest()

    def _make_signed_request(self, payload: str, secret: str, timestamp: str = "1671552777") -> dict:
        return {"paddle-signature": f"ts={timestamp};h1={self._sign(payload, secret, timestamp)}"}

    def _request_globals(self, payload: str, headers: dict | None = None, method: str = "POST") -> dict:
        return {
            "request": {
                "method": method,
                "headers": headers or {},
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def test_valid_signed_webhook(self):
        secret = "pdl_ntfset_test"
        headers = self._make_signed_request(TRANSACTION_PAYLOAD, secret)
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"transaction": "schema_123"},
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], "schema_123")

    def test_second_h1_matches_during_secret_rotation(self):
        secret = "pdl_ntfset_test"
        timestamp = "1671552777"
        wrong = self._sign(TRANSACTION_PAYLOAD, "old_secret", timestamp)
        right = self._sign(TRANSACTION_PAYLOAD, secret, timestamp)
        headers = {"paddle-signature": f"ts={timestamp};h1={wrong};h1={right}"}
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"transaction": "schema_123"},
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], "schema_123")

    def test_multiple_h1_none_matching_returns_400(self):
        timestamp = "1671552777"
        wrong_a = self._sign(TRANSACTION_PAYLOAD, "old_secret", timestamp)
        wrong_b = self._sign(TRANSACTION_PAYLOAD, "older_secret", timestamp)
        headers = {"paddle-signature": f"ts={timestamp};h1={wrong_a};h1={wrong_b}"}
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        res = self.run_function({"signing_secret": "pdl_ntfset_test", "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_invalid_signature_returns_400(self):
        headers = self._make_signed_request(TRANSACTION_PAYLOAD, "wrong_secret")
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        res = self.run_function({"signing_secret": "correct_secret", "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 400, "body": "Bad signature"}}

    def test_missing_signature_returns_400(self):
        globals = self._request_globals(TRANSACTION_PAYLOAD)
        res = self.run_function({"signing_secret": "pdl_ntfset_test", "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 400, "body": "Missing signature"}}

    @parameterized.expand(
        [
            ("no_parts", "garbage"),
            ("missing_h1", "ts=1671552777"),
            ("missing_timestamp", "h1=abcdef"),
        ]
    )
    def test_unparseable_signature_returns_400(self, _name, sig_value):
        globals = self._request_globals(TRANSACTION_PAYLOAD, {"paddle-signature": sig_value})
        res = self.run_function({"signing_secret": "pdl_ntfset_test", "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 400, "body": "Could not parse signature"}}

    def test_recent_timestamp_within_variance_is_accepted(self):
        secret = "pdl_ntfset_test"
        ts = str(int(time.time()) - 60)
        headers = self._make_signed_request(TRANSACTION_PAYLOAD, secret, timestamp=ts)
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"transaction": "schema_123"},
                "maximum_variance_seconds": 3600,
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once()

    def test_stale_timestamp_beyond_variance_is_rejected(self):
        secret = "pdl_ntfset_test"
        ts = str(int(time.time()) - 3600)
        headers = self._make_signed_request(TRANSACTION_PAYLOAD, secret, timestamp=ts)
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"transaction": "schema_123"},
                "maximum_variance_seconds": 5,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Signature timestamp too old"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_maximum_variance_zero_disables_replay_check(self):
        secret = "pdl_ntfset_test"
        ts = str(int(time.time()) - 3600)
        headers = self._make_signed_request(TRANSACTION_PAYLOAD, secret, timestamp=ts)
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"transaction": "schema_123"},
                "maximum_variance_seconds": 0,
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once()

    def test_omitted_variance_skips_replay_check(self):
        # No maximum_variance_seconds input is the shape of every already-deployed function; the
        # drift check must be skipped, not raise on a null comparison (Hog `and` doesn't short-circuit).
        secret = "pdl_ntfset_test"
        ts = str(int(time.time()) - 3600)
        headers = self._make_signed_request(TRANSACTION_PAYLOAD, secret, timestamp=ts)
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"transaction": "schema_123"},
            },
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once()

    def test_non_numeric_timestamp_with_variance_is_rejected(self):
        # A parseable header with a non-numeric ts must 400, not raise (toInt returns null).
        secret = "pdl_ntfset_test"
        sig = self._sign(TRANSACTION_PAYLOAD, secret, timestamp="not-a-number")
        headers = {"paddle-signature": f"ts=not-a-number;h1={sig}"}
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers)
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"transaction": "schema_123"},
                "maximum_variance_seconds": 5,
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 400, "body": "Signature timestamp too old"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand(
        [
            ("null", None),
            ("empty_string", ""),
        ]
    )
    def test_missing_signing_secret_returns_400(self, _name, signing_secret):
        globals = self._request_globals(TRANSACTION_PAYLOAD)
        res = self.run_function({"signing_secret": signing_secret, "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 400, "body": "Signing secret not configured"}}

    def test_bypass_signature_check(self):
        globals = self._request_globals(TRANSACTION_PAYLOAD)
        self.run_function(
            {"signing_secret": "", "bypass_signature_check": True, "schema_mapping": {"transaction": "schema_456"}},
            globals=globals,
        )
        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], "schema_456")

    def test_non_post_request_returns_405(self):
        secret = "pdl_ntfset_test"
        headers = self._make_signed_request(TRANSACTION_PAYLOAD, secret)
        globals = self._request_globals(TRANSACTION_PAYLOAD, headers, method="GET")
        res = self.run_function({"signing_secret": secret, "bypass_signature_check": False}, globals=globals)
        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}

    @parameterized.expand(
        [
            (
                "missing_event_type",
                {"data": {"id": "txn_01"}},
                "No event type found, skipping",
            ),
            (
                "unmapped_entity_type",
                {"event_type": "address.created", "data": {"id": "add_01"}},
                "No schema mapping for event type: address.created, skipping",
            ),
        ]
    )
    def test_unroutable_event_returns_200_without_producing(self, _name, body, expected_message):
        secret = "pdl_ntfset_test"
        payload = json.dumps(body)
        headers = self._make_signed_request(payload, secret)
        globals = self._request_globals(payload, headers)
        res = self.run_function(
            {
                "signing_secret": secret,
                "bypass_signature_check": False,
                "schema_mapping": {"transaction": "schema_123"},
            },
            globals=globals,
        )
        assert res.result == {"httpResponse": {"status": 200, "body": expected_message}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
