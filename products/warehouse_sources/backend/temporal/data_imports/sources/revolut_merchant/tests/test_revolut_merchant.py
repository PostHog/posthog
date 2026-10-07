from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.revolut_merchant import (
    RevolutMerchantResumeConfig,
    revolut_merchant_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.settings import API_VERSION

BASE_URL = "https://merchant.revolut.com/api"


def manager(state: dict | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = state is not None
    result.load_state.return_value = RevolutMerchantResumeConfig(paginator_state=state) if state else None
    return result


def source(endpoint: str, resume_manager: MagicMock) -> SourceResponse:
    return revolut_merchant_source(
        "test-secret-key", "production", endpoint, 1, "test-job", API_VERSION, resume_manager
    )


def items(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


@pytest.mark.parametrize(
    "endpoint,path,terminal",
    [
        ("customers", "customers", {}),
        ("subscriptions", "subscriptions", {"next_page_token": None}),
        ("subscription_plans", "subscription-plans", {"next_page_token": ""}),
    ],
)
def test_cursor_pages_and_checkpoint_after_yield(
    requests_mock: requests_mock.Mocker, endpoint: str, path: str, terminal: dict
) -> None:
    requests_mock.get(
        f"{BASE_URL}/{path}",
        [
            {"json": {endpoint: [{"id": "first"}], "next_page_token": "cursor+/="}},
            {"json": {endpoint: [{"id": "second"}], **terminal}},
        ],
    )
    resume_manager = manager()
    pages = iter(items(source(endpoint, resume_manager)))
    assert next(pages) == [{"id": "first"}]
    resume_manager.save_state.assert_not_called()
    assert next(pages) == [{"id": "second"}]
    assert resume_manager.save_state.call_args.args[0].paginator_state == {"cursor": "cursor+/="}
    assert list(pages) == []
    assert requests_mock.call_count == 2
    assert requests_mock.request_history[0].qs == {"limit": ["500"]}
    assert requests_mock.request_history[1].qs == {"limit": ["500"], "page_token": ["cursor+/="]}
    last_request = requests_mock.last_request
    assert last_request is not None
    assert last_request.headers["Authorization"] == "Bearer test-secret-key"
    assert last_request.headers["Revolut-Api-Version"] == "2026-08-17"


@pytest.mark.parametrize(
    "endpoint,path,body,query",
    [
        ("customers", "customers", {"customers": []}, {"page_token": ["saved-token"], "limit": ["500"]}),
        ("orders", "1.0/orders", [], {"created_before": ["saved-token"], "limit": ["1000"]}),
    ],
)
def test_resume_cursor_is_applied_to_first_request(
    requests_mock: requests_mock.Mocker, endpoint: str, path: str, body: dict | list, query: dict
) -> None:
    requests_mock.get(f"{BASE_URL}/{path}", json=body)
    assert list(items(source(endpoint, manager({"cursor": "saved-token"})))) == []
    last_request = requests_mock.last_request
    assert last_request is not None
    assert last_request.qs == query


def test_orders_continue_from_last_creation_time_until_empty(requests_mock: requests_mock.Mocker) -> None:
    requests_mock.get(
        f"{BASE_URL}/1.0/orders",
        [
            {"json": [{"id": "order-new", "created_at": "2026-01-02T10:00:00.123456Z"}]},
            {"json": [{"id": "order-old", "created_at": "2026-01-01T10:00:00.654321Z"}]},
            {"json": []},
        ],
    )
    rows = [row for page in items(source("orders", manager())) for row in page]
    assert [row["id"] for row in rows] == ["order-new", "order-old"]
    assert requests_mock.request_history[0].qs == {"limit": ["1000"]}
    assert requests_mock.request_history[1].qs["created_before"] == ["2026-01-02t10:00:00.123456z"]
    assert requests_mock.request_history[2].qs["created_before"] == ["2026-01-01t10:00:00.654321z"]


@pytest.mark.parametrize("resume", [False, True])
def test_payments_keep_parent_keys_and_resume_completed_orders(
    requests_mock: requests_mock.Mocker, resume: bool
) -> None:
    requests_mock.get(
        f"{BASE_URL}/1.0/orders",
        [
            {"json": [{"id": "order-a", "created_at": "2026-01-02T00:00:00Z"}]},
            {"json": [{"id": "order-b", "created_at": "2026-01-01T00:00:00Z"}]},
            {"json": []},
        ],
    )
    first_payment = requests_mock.get(f"{BASE_URL}/orders/order-a/payments", json=[{"id": "payment-1"}])
    second_payment = requests_mock.get(f"{BASE_URL}/orders/order-b/payments", json=[{"id": "payment-1"}])
    resume_manager = manager(
        {"completed": ["/orders/order-a/payments"], "current": None, "child_state": None} if resume else None
    )
    result = source("payments", resume_manager)
    rows = [row for page in items(result) for row in page]
    expected = [{"id": "payment-1", "order_id": "order-b"}]
    if not resume:
        expected.insert(0, {"id": "payment-1", "order_id": "order-a"})
    assert rows == expected
    assert result.primary_keys is not None
    assert len({tuple(row[key] for key in result.primary_keys) for row in rows}) == len(expected)
    assert first_payment.call_count == (0 if resume else 1)
    assert second_payment.call_count == 1
    second_payment_request = second_payment.last_request
    assert second_payment_request is not None
    assert second_payment_request.qs == {}
    assert resume_manager.save_state.call_args.args[0].paginator_state["completed"] == [
        "/orders/order-a/payments",
        "/orders/order-b/payments",
    ]


@pytest.mark.parametrize("endpoint,path", [("customers", "customers"), ("orders", "1.0/orders")])
def test_changed_response_shape_fails_instead_of_replacing_with_empty_table(
    requests_mock: requests_mock.Mocker, endpoint: str, path: str
) -> None:
    requests_mock.get(f"{BASE_URL}/{path}", json={"unexpected": []})
    with pytest.raises(ValueError):
        list(items(source(endpoint, manager())))


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


@pytest.mark.parametrize("status", [429, 503])
def test_transient_statuses_retry_without_advancing_cursor(requests_mock: requests_mock.Mocker, status: int) -> None:
    requests_mock.get(
        f"{BASE_URL}/customers",
        [
            {"status_code": status, "headers": {"Retry-After": "0"}},
            {"json": {"customers": [{"id": "customer-1"}]}},
        ],
    )
    assert list(items(source("customers", manager()))) == [[{"id": "customer-1"}]]
    assert requests_mock.call_count == 2
    assert requests_mock.request_history[0].qs == requests_mock.request_history[1].qs


def test_unexpected_probe_failure_is_not_a_credential_error(requests_mock: requests_mock.Mocker) -> None:
    requests_mock.get(f"{BASE_URL}/customers", status_code=404)
    with pytest.raises(HTTPError):
        validate_credentials("test-secret-key", "production", API_VERSION)
