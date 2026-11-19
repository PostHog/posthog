from datetime import UTC, datetime, timedelta

import pytest

import requests_mock
from requests import HTTPError

from products.warehouse_sources.sources.revolut_merchant.revolut_merchant import (
    RevolutMerchantResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.sources.revolut_merchant.settings import API_VERSION, CREATED_DATE_PAGE_SIZE
from products.warehouse_sources.sources.revolut_merchant.source import RevolutMerchantSource
from products.warehouse_sources.sources.sdk.testing import DriveResult, Script, ScriptedResponse, SourceDriver, route

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


def created_rows(prefix: str, start: datetime, count: int, step: timedelta) -> list[dict[str, str]]:
    return [{"id": f"{prefix}-{i}", "created_at": (start + step * i).isoformat()} for i in range(count)]


@pytest.mark.parametrize("endpoint", ["disputes", "payouts"])
@pytest.mark.parametrize(
    "step,param", [(timedelta(minutes=-1), "to_created_date"), (timedelta(minutes=1), "from_created_date")]
)
@pytest.mark.parametrize("resume", [False, True])
def test_created_date_pages_keep_rows_that_share_the_boundary(
    endpoint: str, step: timedelta, param: str, resume: bool
) -> None:
    boundary = datetime(2026, 1, 1, tzinfo=UTC)
    first_page = [
        *created_rows("a", boundary - step * (CREATED_DATE_PAGE_SIZE - 1), CREATED_DATE_PAGE_SIZE - 1, step),
        {"id": "boundary-1", "created_at": boundary.isoformat()},
    ]
    last_page = [
        {"id": "boundary-1", "created_at": boundary.isoformat()},
        {"id": "boundary-2", "created_at": boundary.isoformat()},
        {"id": "after", "created_at": (boundary + step).isoformat()},
    ]
    bound = "2026-01-01T00:00:00.000000Z"
    result = run(
        endpoint,
        route(
            {
                f"/{endpoint}": [
                    ScriptedResponse(json=page) for page in ([last_page] if resume else [first_page, last_page])
                ]
            }
        ),
        RevolutMerchantResumeConfig(paginator_state={"param": param, "value": bound, "boundary_ids": ["boundary-1"]})
        if resume
        else None,
    )

    assert result.raised is None
    assert result.rows == (last_page[1:] if resume else first_page + last_page[1:])
    assert result.requests[-1].query == {"limit": ("500",), param: (bound,)}
    assert len(result.requests) == (1 if resume else 2)


def test_created_date_pagination_fails_when_the_window_does_not_move() -> None:
    page = created_rows("a", datetime(2026, 1, 1, tzinfo=UTC), CREATED_DATE_PAGE_SIZE, timedelta(minutes=-1))
    result = run("disputes", route({"/disputes": [ScriptedResponse(json=page), ScriptedResponse(json=page)]}))

    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == 2


def test_subscription_cycles_page_each_subscription_and_keep_parent_keys() -> None:
    result = run(
        "subscription_cycles",
        route(
            {
                "/subscriptions": [
                    ScriptedResponse(
                        json={"subscriptions": [{"id": "sub-a"}, {"id": "sub-b"}], "next_page_token": None}
                    )
                ],
                "/subscriptions/sub-a/cycles": [
                    ScriptedResponse(
                        json={"cycles": [{"id": "cycle-1", "subscription_id": "sub-a"}], "next_page_token": "t"}
                    ),
                    ScriptedResponse(json={"cycles": [{"id": "cycle-2", "subscription_id": "sub-a"}]}),
                ],
                "/subscriptions/sub-b/cycles": [
                    ScriptedResponse(json={"cycles": [{"id": "cycle-1", "subscription_id": "sub-b"}]}),
                ],
            }
        ),
    )

    assert result.raised is None
    assert result.response is not None
    assert result.response.primary_keys is not None
    keys = [tuple(row[key] for key in result.response.primary_keys) for row in result.rows]
    assert keys == [("sub-a", "cycle-1"), ("sub-a", "cycle-2"), ("sub-b", "cycle-1")]
    cycle_queries = [request.query for request in result.requests if request.path.endswith("/cycles")]
    assert cycle_queries == [{"limit": ("500",)}, {"limit": ("500",), "page_token": ("t",)}, {"limit": ("500",)}]


@pytest.mark.parametrize("endpoint", ["customers", "orders", "payouts", "subscription_usages", "disputes"])
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


@pytest.mark.parametrize(
    "schema_name,parent_path,parent_page,child_path,child_page",
    [
        ("payments", "/1.0/orders", [{"id": "order-a"}], "/orders/order-a/payments", []),
        (
            "subscription_cycles",
            "/subscriptions",
            {"subscriptions": [{"id": "sub-a"}]},
            "/subscriptions/sub-a/cycles",
            {"cycles": []},
        ),
    ],
)
@pytest.mark.parametrize("empty_parent,status,valid", [(True, 200, True), (False, 200, True), (False, 403, False)])
def test_child_permission_probe_uses_an_existing_parent(
    requests_mock: requests_mock.Mocker,
    schema_name: str,
    parent_path: str,
    parent_page: object,
    child_path: str,
    child_page: object,
    empty_parent: bool,
    status: int,
    valid: bool,
) -> None:
    empty_page = [] if isinstance(parent_page, list) else {"subscriptions": []}
    requests_mock.get(f"{BASE_URL}{parent_path}", json=empty_page if empty_parent else parent_page)
    child = requests_mock.get(f"{BASE_URL}{child_path}", status_code=status, json=child_page)
    result, error = validate_credentials("test-secret-key", "production", API_VERSION, schema_name)
    assert result is valid
    assert child.call_count == (0 if empty_parent else 1)
    if not valid:
        assert error and "permissions" in error


@pytest.mark.parametrize(
    "api_key,environment,schema_name,message",
    [
        ("", "production", None, "Secret API key"),
        ("test key", "production", None, "Secret API key"),
        ("test\nkey", "production", None, "Secret API key"),
        ("test\u200bkey", "production", None, "Secret API key"),
        ("test-secret-key", "sandbox", "disputes", "Production environment"),
    ],
)
def test_unusable_setup_is_rejected_without_http(
    requests_mock: requests_mock.Mocker, api_key: str, environment: str, schema_name: str | None, message: str
) -> None:
    valid, error = validate_credentials(api_key, environment, API_VERSION, schema_name)
    assert not valid
    assert error and message in error
    assert requests_mock.call_count == 0


def test_unexpected_probe_failure_is_not_a_credential_error(requests_mock: requests_mock.Mocker) -> None:
    requests_mock.get(f"{BASE_URL}/customers", status_code=404)
    with pytest.raises(HTTPError):
        validate_credentials("test-secret-key", "production", API_VERSION)
