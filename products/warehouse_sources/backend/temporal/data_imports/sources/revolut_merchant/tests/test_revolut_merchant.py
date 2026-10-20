import pytest

import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.revolut_merchant import (
    RevolutMerchantResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.settings import API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.source import (
    RevolutMerchantSource,
)

BASE_URL = "https://merchant.revolut.com/api"


def run(endpoint: str, script: Script, resume_state: RevolutMerchantResumeConfig | None = None) -> DriveResult:
    source = RevolutMerchantSource()
    config = source.parse_config({"api_key": "test-secret-key", "environment": "production"})
    return SourceDriver(source, config).run(endpoint, script, resume_state=resume_state)


@pytest.mark.parametrize("resume", [False, True])
def test_payments_keep_parent_keys_and_resume_completed_orders(resume: bool) -> None:
    result = run(
        "payments",
        route(
            {
                "/1.0/orders": [
                    ScriptedResponse(json=[{"id": "order-a", "created_at": "2026-01-02T00:00:00Z"}]),
                    ScriptedResponse(json=[{"id": "order-b", "created_at": "2026-01-01T00:00:00Z"}]),
                    ScriptedResponse(json=[]),
                ],
                "/orders/order-a/payments": [ScriptedResponse(json=[{"id": "payment-1"}])],
                "/orders/order-b/payments": [ScriptedResponse(json=[{"id": "payment-1"}])],
            }
        ),
        RevolutMerchantResumeConfig(
            paginator_state={"completed": ["/orders/order-a/payments"], "current": None, "child_state": None}
        )
        if resume
        else None,
    )
    expected = [{"id": "payment-1", "order_id": "order-b"}]
    if not resume:
        expected.insert(0, {"id": "payment-1", "order_id": "order-a"})
    assert result.raised is None
    assert result.rows == expected
    assert result.response is not None
    assert result.response.primary_keys is not None
    assert len({tuple(row[key] for key in result.response.primary_keys) for row in result.rows}) == len(expected)
    assert result.paths.count("/api/orders/order-a/payments") == (0 if resume else 1)
    assert result.paths.count("/api/orders/order-b/payments") == 1
    second_payment_request = next(request for request in result.requests if request.path.endswith("order-b/payments"))
    assert second_payment_request.query == {}
    assert result.saved_states[-1].paginator_state["completed"] == [
        "/orders/order-a/payments",
        "/orders/order-b/payments",
    ]


@pytest.mark.parametrize("endpoint", ["customers", "orders"])
def test_changed_response_shape_fails_instead_of_replacing_with_empty_table(endpoint: str) -> None:
    result = run(endpoint, [ScriptedResponse(json={"unexpected": []})])

    assert isinstance(result.raised, ValueError)


@pytest.mark.parametrize(
    "status,schema_name,valid,message",
    [
        (200, None, True, None),
        (401, None, False, "Secret API key"),
        (403, None, True, None),
        (403, "customers", False, "permissions"),
        (400, "customers", False, "API version"),
    ],
)
def test_credential_probe_status_mapping(
    requests_mock: requests_mock.Mocker, status: int, schema_name: str | None, valid: bool, message: str | None
) -> None:
    requests_mock.get(f"{BASE_URL}/customers", status_code=status, json={"customers": []})
    result, error = validate_credentials("test-secret-key", "production", API_VERSION, schema_name)
    assert result is valid
    if message:
        assert error is not None and message in error
    else:
        assert error is None
    assert requests_mock.call_count == 1


@pytest.mark.parametrize("empty_orders,status,valid", [(True, 200, True), (False, 200, True), (False, 403, False)])
def test_payment_permission_probe_uses_an_existing_order(
    requests_mock: requests_mock.Mocker, empty_orders: bool, status: int, valid: bool
) -> None:
    requests_mock.get(f"{BASE_URL}/1.0/orders", json=[] if empty_orders else [{"id": "order-a"}])
    child = requests_mock.get(f"{BASE_URL}/orders/order-a/payments", status_code=status, json=[])
    result, error = validate_credentials("test-secret-key", "production", API_VERSION, "payments")
    assert result is valid
    assert child.call_count == (0 if empty_orders else 1)
    if not valid:
        assert error and "permissions" in error


@pytest.mark.parametrize("api_key", ["", "test key", "test\nkey", "test\u200bkey"])
def test_invalid_header_key_is_rejected_without_http(requests_mock: requests_mock.Mocker, api_key: str) -> None:
    valid, error = validate_credentials(api_key, "production", API_VERSION)
    assert not valid
    assert error and "Secret API key" in error
    assert requests_mock.call_count == 0


def test_unexpected_probe_failure_is_not_a_credential_error(requests_mock: requests_mock.Mocker) -> None:
    requests_mock.get(f"{BASE_URL}/customers", status_code=404)
    with pytest.raises(HTTPError):
        validate_credentials("test-secret-key", "production", API_VERSION)
