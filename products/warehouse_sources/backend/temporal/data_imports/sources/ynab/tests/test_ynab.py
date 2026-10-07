from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.source import YnabSource
from products.warehouse_sources.backend.temporal.data_imports.sources.ynab.ynab import (
    YnabResumeConfig,
    validate_credentials,
    ynab_source,
)

BASE_URL = "https://api.ynab.com/v1/"


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def rows_for(endpoint: str, manager: MagicMock) -> Iterator[list[dict[str, Any]]]:
    response = ynab_source("fake-ynab-token", endpoint, "v1", 1, "test-job", manager)
    return iter(cast(Iterable[list[dict[str, Any]]], response.items()))


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
    ],
)
@responses.activate
def test_full_refresh_across_plans(
    endpoint: str, path: str, data: dict[str, Any], row: dict[str, Any], manager: MagicMock
) -> None:
    responses.get(BASE_URL + "plans", json={"data": {"plans": [{"id": "plan-1"}, {"id": "plan-2"}]}})
    for plan in ["plan-1", "plan-2"]:
        responses.get(BASE_URL + f"plans/{plan}/{path}", json={"data": {**data, "server_knowledge": 42}})

    batches = list(rows_for(endpoint, manager))

    assert batches == [[{**row, "plan_id": "plan-1"}], [{**row, "plan_id": "plan-2"}]]
    response = ynab_source("fake-ynab-token", endpoint, "v1", 1, "test-job", manager)
    assert response.primary_keys is not None
    keys = [tuple(item[key] for key in response.primary_keys) for batch in batches for item in batch]
    assert len(set(keys)) == 2
    assert len(responses.calls) == 3
    for call in responses.calls:
        assert call.request.headers["Authorization"] == "Bearer fake-ynab-token"
        query = parse_qs(urlsplit(call.request.url).query)
        expected = (
            {"since_date": ["0001-01-01"]} if endpoint == "transactions" and "/transactions" in call.request.url else {}
        )
        assert query == expected


@responses.activate
def test_plans_list_and_empty_account(manager: MagicMock) -> None:
    responses.get(BASE_URL + "plans", json={"data": {"plans": [{"id": "plan-1", "name": "Example plan"}]}})
    assert list(rows_for("plans", manager)) == [[{"id": "plan-1", "name": "Example plan"}]]
    responses.replace(responses.GET, BASE_URL + "plans", json={"data": {"plans": []}})
    assert list(rows_for("accounts", manager)) == []
    assert len(responses.calls) == 2
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("groups", [[], [{"id": "group-1", "categories": []}]])
@responses.activate
def test_empty_categories_complete_the_plan(groups: list[dict[str, Any]], manager: MagicMock) -> None:
    responses.get(BASE_URL + "plans", json={"data": {"plans": [{"id": "plan-1"}]}})
    responses.get(BASE_URL + "plans/plan-1/categories", json={"data": {"category_groups": groups}})
    assert list(rows_for("categories", manager)) == []
    assert manager.save_state.call_args.args[0].completed == ["plans/plan-1/categories"]


@responses.activate
def test_resume_skips_completed_plans_and_checkpoints_after_yield(manager: MagicMock) -> None:
    responses.get(BASE_URL + "plans", json={"data": {"plans": [{"id": "plan-1"}, {"id": "plan-2"}]}})
    for plan in ["plan-1", "plan-2"]:
        responses.get(BASE_URL + f"plans/{plan}/accounts", json={"data": {"accounts": [{"id": "account-1"}]}})
    batches = rows_for("accounts", manager)
    assert next(batches)[0]["plan_id"] == "plan-1"
    manager.save_state.assert_not_called()
    assert next(batches)[0]["plan_id"] == "plan-2"
    checkpoint = manager.save_state.call_args.args[0]
    assert checkpoint == YnabResumeConfig(completed=["plans/plan-1/accounts"])
    del batches

    manager.can_resume.return_value = True
    manager.load_state.return_value = checkpoint
    assert list(rows_for("accounts", manager)) == [[{"id": "account-1", "plan_id": "plan-2"}]]
    assert [call.request.url for call in responses.calls].count(BASE_URL + "plans/plan-1/accounts") == 1
    assert manager.save_state.call_args.args[0].completed == ["plans/plan-1/accounts", "plans/plan-2/accounts"]


@pytest.mark.parametrize(
    "status,schema_name,valid,message",
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "accounts", False, "permissions"),
    ],
)
@responses.activate
def test_credential_status_mapping(status: int, schema_name: str | None, valid: bool, message: str | None) -> None:
    responses.get(BASE_URL + "user", status=status, json={"data": {"user": {"id": "user-1"}}})
    result, reason = validate_credentials("fake-ynab-token", "v1", schema_name)
    assert result is valid
    if message is not None:
        assert reason is not None and message in reason
    else:
        assert reason is None
    assert responses.calls[0].request.headers["Authorization"] == "Bearer fake-ynab-token"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
@responses.activate
def test_sync_errors_keep_auth_terminal_and_outages_retryable(status: int, manager: MagicMock) -> None:
    responses.get(BASE_URL + "plans", status=status, json={"error": {"id": str(status)}})
    exception = RESTClientRetryableError if status in (429, 500) else HTTPError
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.RESTClient._send_request.retry.sleep"
        ),
        pytest.raises(exception) as caught,
    ):
        list(rows_for("plans", manager))
    mappings = YnabSource().get_non_retryable_errors()
    matched = [message for pattern, message in mappings.items() if pattern in str(caught.value)]
    assert bool(matched) is (status in (401, 403))
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("status", [404, 429, 500])
@responses.activate
def test_credential_probe_propagates_non_auth_failures(status: int) -> None:
    responses.get(BASE_URL + "user", status=status, json={"error": {"id": str(status)}})
    exception = RESTClientRetryableError if status in (429, 500) else HTTPError
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.RESTClient._send_request.retry.sleep"
        ),
        pytest.raises(exception),
    ):
        validate_credentials("fake-ynab-token", "v1", None)
