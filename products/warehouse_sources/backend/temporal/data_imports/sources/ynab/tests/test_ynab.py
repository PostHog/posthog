from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ynab import YnabSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.source import YnabSource
from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.ynab import (
    YnabResumeConfig,
    validate_credentials,
)


@pytest.fixture
def driver() -> SourceDriver:
    return SourceDriver(YnabSource(), YnabSourceConfig(api_key="fake-ynab-token"))


def _accounts_script() -> Any:
    return route(
        {
            "/v1/plans": [ScriptedResponse(json={"data": {"plans": [{"id": "plan-1"}, {"id": "plan-2"}]}})],
            "/v1/plans/plan-1/accounts": [ScriptedResponse(json={"data": {"accounts": [{"id": "account-1"}]}})],
            "/v1/plans/plan-2/accounts": [ScriptedResponse(json={"data": {"accounts": [{"id": "account-1"}]}})],
        }
    )


@pytest.mark.parametrize(
    "endpoint,path,data,row",
    [
        (
            "accounts",
            "accounts",
            {"accounts": [{"id": "record-1", "balance": 12345}]},
            {"id": "record-1", "balance": 12345},
        ),
        (
            "payees",
            "payees",
            {"payees": [{"id": "record-1", "name": "Example shop"}]},
            {"id": "record-1", "name": "Example shop"},
        ),
        (
            "payee_locations",
            "payee_locations",
            {"payee_locations": [{"id": "record-1", "payee_id": "payee-1"}]},
            {"id": "record-1", "payee_id": "payee-1"},
        ),
        (
            "months",
            "months",
            {"months": [{"month": "2020-01-01", "income": 100000}]},
            {"month": "2020-01-01", "income": 100000},
        ),
        (
            "categories",
            "categories",
            {
                "category_groups": [
                    {"id": "group-1", "categories": [{"id": "record-1", "category_group_id": "group-1"}]}
                ]
            },
            {"id": "record-1", "category_group_id": "group-1"},
        ),
        (
            "category_groups",
            "categories",
            {"category_groups": [{"id": "record-1", "categories": []}]},
            {"id": "record-1", "categories": []},
        ),
        (
            "transactions",
            "transactions",
            {
                "transactions": [
                    {
                        "id": "record-1",
                        "date": "2000-01-01",
                        "amount": -1250,
                        "subtransactions": [{"id": "split-1", "amount": -1250}],
                    }
                ]
            },
            {
                "id": "record-1",
                "date": "2000-01-01",
                "amount": -1250,
                "subtransactions": [{"id": "split-1", "amount": -1250}],
            },
        ),
        (
            "scheduled_transactions",
            "scheduled_transactions",
            {"scheduled_transactions": [{"id": "record-1", "frequency": "monthly"}]},
            {"id": "record-1", "frequency": "monthly"},
        ),
        (
            "money_movements",
            "money_movements",
            {"money_movements": [{"id": "record-1", "amount": 5000, "to_category_id": "category-1"}]},
            {"id": "record-1", "amount": 5000, "to_category_id": "category-1"},
        ),
        (
            "money_movement_groups",
            "money_movement_groups",
            {"money_movement_groups": [{"id": "record-1", "group_created_at": "2024-01-02T03:04:05Z"}]},
            {"id": "record-1", "group_created_at": "2024-01-02T03:04:05Z"},
        ),
    ],
)
def test_full_refresh_across_plans(
    endpoint: str, path: str, data: dict[str, Any], row: dict[str, Any], driver: SourceDriver
) -> None:
    result = driver.run(
        endpoint,
        route(
            {
                "/v1/plans": [ScriptedResponse(json={"data": {"plans": [{"id": "plan-1"}, {"id": "plan-2"}]}})],
                **{
                    f"/v1/plans/{plan}/{path}": [ScriptedResponse(json={"data": {**data, "server_knowledge": 42}})]
                    for plan in ["plan-1", "plan-2"]
                },
            }
        ),
    )

    assert result.items == [[{**row, "plan_id": "plan-1"}], [{**row, "plan_id": "plan-2"}]]
    assert result.response is not None
    assert result.response.primary_keys is not None
    keys = [tuple(item[key] for key in result.response.primary_keys) for batch in result.items for item in batch]
    assert len(set(keys)) == 2
    assert len(result.requests) == 3
    for request in result.requests:
        assert request.headers["authorization"] == "Bearer fake-ynab-token"
        expected = (
            {"since_date": ("0001-01-01",)} if endpoint == "transactions" and "/transactions" in request.url else {}
        )
        assert dict(request.query) == expected


def test_plans_list_and_empty_account(driver: SourceDriver) -> None:
    plans = driver.run(
        "plans", [ScriptedResponse(json={"data": {"plans": [{"id": "plan-1", "name": "Example plan"}]}})]
    )
    assert plans.items == [[{"id": "plan-1", "name": "Example plan"}]]
    accounts = driver.run("accounts", [ScriptedResponse(json={"data": {"plans": []}})])
    assert accounts.items == []
    assert len(plans.requests) + len(accounts.requests) == 2
    assert plans.saved_states == []
    assert accounts.saved_states == []


def _month_detail(categories: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"month": {"categories": categories}}})


@pytest.mark.parametrize(
    "plan,resume_state,expected_rows",
    [
        (
            {"id": "plan-1", "first_month": "2023-11-01", "last_month": "2024-01-01"},
            None,
            [("plan-1", "2023-11-01"), ("plan-1", "2023-12-01"), ("plan-1", "2024-01-01")],
        ),
        (
            {"id": "plan-1", "first_month": "2023-11-01", "last_month": "2024-01-01"},
            YnabResumeConfig(completed=["plans/plan-1/months/2023-11-01"]),
            [("plan-1", "2023-12-01"), ("plan-1", "2024-01-01")],
        ),
        ({"id": "plan-1", "first_month": "2024-01-01", "last_month": "2024-01-01"}, None, [("plan-1", "2024-01-01")]),
        ({"id": "plan-1", "first_month": None, "last_month": None}, None, []),
        ({"id": "plan-1"}, None, []),
    ],
)
def test_month_categories_cover_each_plan_month(
    plan: dict[str, Any],
    resume_state: YnabResumeConfig | None,
    expected_rows: list[tuple[str, str]],
    driver: SourceDriver,
) -> None:
    category = {"id": "category-1", "budgeted": 1000, "activity": -500, "balance": 500}
    result = driver.run(
        "month_categories",
        route(
            {
                "/v1/plans": [ScriptedResponse(json={"data": {"plans": [plan, {"id": "plan-2"}]}})],
                **{
                    f"/v1/plans/plan-1/months/{month}": [_month_detail([category])]
                    for month in ["2023-11-01", "2023-12-01", "2024-01-01"]
                },
            }
        ),
        resume_state=resume_state,
    )

    rows = [row for batch in result.items for row in batch]
    assert [(row["plan_id"], row["month"]) for row in rows] == expected_rows
    assert all(row["id"] == "category-1" and row["balance"] == 500 for row in rows)
    assert result.response is not None and result.response.primary_keys is not None
    assert len({tuple(row[key] for key in result.response.primary_keys) for row in rows}) == len(rows)
    assert result.paths == ["/v1/plans", *[f"/v1/plans/plan-1/months/{month}" for _, month in expected_rows]]
    assert all(dict(request.query) == {} for request in result.requests)
    if expected_rows:
        assert result.saved_states[-1].completed[-1] == f"plans/plan-1/months/{expected_rows[-1][1]}"


def test_month_categories_skip_missing_month(driver: SourceDriver) -> None:
    result = driver.run(
        "month_categories",
        route(
            {
                "/v1/plans": [
                    ScriptedResponse(
                        json={
                            "data": {
                                "plans": [{"id": "plan-1", "first_month": "2024-01-01", "last_month": "2024-02-01"}]
                            }
                        }
                    )
                ],
                "/v1/plans/plan-1/months/2024-01-01": [
                    ScriptedResponse(status=404, json={"error": {"id": "404.2", "name": "resource_not_found"}})
                ],
                "/v1/plans/plan-1/months/2024-02-01": [_month_detail([{"id": "category-1"}])],
            }
        ),
    )

    assert result.raised is None
    assert result.items == [[{"id": "category-1", "plan_id": "plan-1", "month": "2024-02-01"}]]
    assert result.saved_states[-1].completed == [
        "plans/plan-1/months/2024-01-01",
        "plans/plan-1/months/2024-02-01",
    ]


@pytest.mark.parametrize("groups", [[], [{"id": "group-1", "categories": []}]])
def test_empty_categories_complete_the_plan(groups: list[dict[str, Any]], driver: SourceDriver) -> None:
    result = driver.run(
        "categories",
        route(
            {
                "/v1/plans": [ScriptedResponse(json={"data": {"plans": [{"id": "plan-1"}]}})],
                "/v1/plans/plan-1/categories": [ScriptedResponse(json={"data": {"category_groups": groups}})],
            }
        ),
    )
    assert result.items == []
    assert result.saved_states[-1].completed == ["plans/plan-1/categories"]


def test_resume_skips_completed_plans_and_checkpoints_after_yield(driver: SourceDriver) -> None:
    first = driver.run("accounts", _accounts_script())
    assert [batch[0]["plan_id"] for batch in first.items] == ["plan-1", "plan-2"]
    checkpoint = YnabResumeConfig(completed=["plans/plan-1/accounts"])
    assert first.saved_states == [
        checkpoint,
        YnabResumeConfig(completed=["plans/plan-1/accounts", "plans/plan-2/accounts"]),
    ]
    assert first.committed_states == first.saved_states
    assert first.paths.count("/v1/plans/plan-1/accounts") == 1

    resumed = driver.run("accounts", _accounts_script(), resume_state=checkpoint)
    assert resumed.items == [[{"id": "account-1", "plan_id": "plan-2"}]]
    assert "/v1/plans/plan-1/accounts" not in resumed.paths
    assert resumed.saved_states[-1].completed == ["plans/plan-1/accounts", "plans/plan-2/accounts"]


@pytest.mark.parametrize(
    "status,schema_name,valid,message",
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "accounts", False, "permissions"),
    ],
)
def test_credential_status_mapping(status: int, schema_name: str | None, valid: bool, message: str | None) -> None:
    with scripted_network(
        always(ScriptedResponse(status=status, json={"data": {"user": {"id": "user-1"}}}))
    ) as network:
        result, reason = validate_credentials("fake-ynab-token", "v1", schema_name)
    assert result is valid
    if message is not None:
        assert reason is not None and message in reason
    else:
        assert reason is None
    assert network.requests_log[0].headers["authorization"] == "Bearer fake-ynab-token"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_sync_errors_keep_auth_terminal_and_outages_retryable(status: int, driver: SourceDriver) -> None:
    result = driver.run("plans", always(ScriptedResponse(status=status, json={"error": {"id": str(status)}})))
    exception = RESTClientRetryableError if status in (429, 500) else HTTPError
    assert isinstance(result.raised, exception)
    mappings = YnabSource().get_non_retryable_errors()
    matched = [message for pattern, message in mappings.items() if pattern in str(result.raised)]
    assert bool(matched) is (status in (401, 403))
    assert result.saved_states == []


@pytest.mark.parametrize("status", [404, 429, 500])
def test_credential_probe_propagates_non_auth_failures(status: int) -> None:
    exception = RESTClientRetryableError if status in (429, 500) else HTTPError
    with (
        scripted_network(always(ScriptedResponse(status=status, json={"error": {"id": str(status)}}))),
        pytest.raises(exception),
    ):
        validate_credentials("fake-ynab-token", "v1", None)
