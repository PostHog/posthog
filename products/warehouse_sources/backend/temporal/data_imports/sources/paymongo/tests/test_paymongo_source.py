import hmac
import json
import time
import hashlib
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from posthog.cdp.validation import compile_hog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paymongo import (
    PaymongoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paymongo.source import PaymongoSource

from common.hogvm.python.execute import execute_bytecode


@pytest.mark.parametrize("operation", ["create_webhook", "delete_webhook"])
def test_webhook_failures_do_not_expose_vendor_body(operation: str) -> None:
    response = Response()
    response.status_code = 403
    response.reason = "Forbidden"
    response.url = "https://api.paymongo.com/v1/webhooks"
    response._content = b'{"errors": [{"detail": "fake-sensitive-response"}]}'
    with patch("requests.sessions.Session.send", return_value=response):
        result = getattr(PaymongoSource(), operation)(
            PaymongoSourceConfig(api_key="fake"), "https://example.com/hook", 1
        )
    assert not result.success
    assert "HTTP 403" in result.error
    assert "fake-sensitive-response" not in result.error


def test_unknown_schema_fails_before_network() -> None:
    with patch("requests.sessions.Session.send") as send:
        with pytest.raises(UnknownResourceError, match="missing_table"):
            PaymongoSource().validate_credentials(PaymongoSourceConfig(api_key="fake"), 1, schema_name="missing_table")
        send.assert_not_called()


@pytest.fixture(scope="module")
def webhook_bytecode() -> list[Any]:
    return compile_hog(PaymongoSource().webhook_template.code, "warehouse_source_webhook")


@pytest.mark.parametrize("livemode", [True, False])
@pytest.mark.parametrize(
    "case,expected_status",
    [
        ("valid", None),
        ("refund", None),
        ("bad_signature", 401),
        ("expired", 401),
        ("wrong_mode", 401),
        ("missing_secret", 200),
        ("unselected", 200),
        ("unrelated", 200),
        ("get", 405),
    ],
)
def test_webhook_verifies_signature_and_routes_payment(
    webhook_bytecode: list[Any], livemode: bool, case: str, expected_status: int | None
) -> None:
    source = PaymongoSource()
    timestamp = str(int(time.time()) - (600 if case == "expired" else 0))
    payload: dict[str, Any] = {
        "data": {
            "id": "evt_fake",
            "attributes": {
                "type": "payment.paid" if case != "unrelated" else "unrelated.created",
                "livemode": livemode,
                "created_at": int(timestamp),
                "data": {"id": "pay_fake", "type": "payment", "attributes": {"status": "paid"}},
            },
        }
    }
    if case == "refund":
        payload["data"]["attributes"]["type"] = "payment.refund.updated"
        payload["data"]["attributes"]["data"] = {
            "id": "ref_fake",
            "type": "refund",
            "attributes": {"payment_id": "pay_fake"},
        }
    raw = json.dumps(payload)
    signature = hmac.new(b"fake-secret", f"{timestamp}.{raw}".encode(), hashlib.sha256).hexdigest()
    if case == "bad_signature":
        signature = "bad"
    mode = "li" if livemode else "te"
    if case == "wrong_mode":
        mode = "te" if livemode else "li"
    producer = MagicMock()
    result = execute_bytecode(
        webhook_bytecode,
        globals={
            "request": {
                "method": "GET" if case == "get" else "POST",
                "body": payload,
                "stringBody": raw,
                "headers": {"paymongo-signature": f"t={timestamp},{mode}={signature}"},
            },
            "inputs": {
                "signing_secret": "" if case == "missing_secret" else "fake-secret",
                "schema_mapping": {}
                if case == "unselected"
                else {source.webhook_mapping_key("payments"): "schema_fake"},
            },
        },
        functions={"produceToWarehouseWebhooks": producer},
    ).result
    if expected_status is None:
        producer.assert_called_once_with(payload, "schema_fake")
    else:
        producer.assert_not_called()
        assert result["httpResponse"]["status"] == expected_status
