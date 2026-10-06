from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mono import MonoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mono.mono import (
    MonoResumeConfig,
    mono_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mono.source import MonoSource

BASE_URL = "https://api.withmono.com/v2"
CONFIG = MonoSourceConfig(api_key="test_sk_fake_mono_key", start_date="2020-01-01")


def manager(resume: MonoResumeConfig | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = resume is not None
    result.load_state.return_value = resume
    return result


def page(rows: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    return {"status": "successful", "data": rows, "meta": {"next": next_url}}


def source(endpoint: str, resume_manager: MagicMock, **kwargs: Any) -> SourceResponse:
    return mono_source(
        config=CONFIG,
        endpoint=endpoint,
        team_id=1,
        job_id="mono-test-job",
        api_version="v2",
        resumable_source_manager=resume_manager,
        **kwargs,
    )


def rows(response: SourceResponse) -> list[dict[str, Any]]:
    return [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]


@pytest.mark.parametrize("endpoint", ["customers", "accounts"])
@pytest.mark.parametrize("terminal_rows", [[], [{"id": "row-2"}]])
def test_list_pagination_auth_and_checkpoint(endpoint: str, terminal_rows: list[dict[str, Any]]) -> None:
    resume_manager = manager()
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/{endpoint}?page=1",
            json=page([{"id": "row-1"}], f"{BASE_URL}/{endpoint}?page=2"),
            complete_qs=True,
        )
        http.get(f"{BASE_URL}/{endpoint}?page=2", json=page(terminal_rows), complete_qs=True)
        response = source(endpoint, resume_manager)
        assert rows(response) == [{"id": "row-1"}, *terminal_rows]
        assert http.call_count == 2
        assert all(request.headers["mono-sec-key"] == CONFIG.api_key for request in http.request_history)
        assert all("x-real-time" not in request.headers for request in http.request_history)
    resume_manager.save_state.assert_called_once_with(MonoResumeConfig(paginator_state={"page": 2}))
    resume_manager.clear_state.assert_not_called()
    assert response.on_complete is not None
    response.on_complete()
    resume_manager.clear_state.assert_called_once()


@pytest.mark.parametrize("endpoint", ["customers", "accounts"])
def test_resumes_list_at_saved_page(endpoint: str) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/{endpoint}?page=4", json=page([{"id": "row-4"}]), complete_qs=True)
        assert rows(source(endpoint, manager(MonoResumeConfig(paginator_state={"page": 4})))) == [{"id": "row-4"}]
        assert http.call_count == 1


@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    "incremental,watermark,expected_start",
    [
        (False, "2026-06-10T15:00:00Z", "01-01-2020"),
        (True, None, "01-01-2020"),
        (True, "2026-06-10T15:00:00Z", "09-06-2026"),
        (True, datetime(2026, 6, 10, 15, tzinfo=UTC), "09-06-2026"),
        (True, "2019-01-01T00:00:00Z", "01-01-2020"),
        (True, "2026-06-15T11:00:00Z", "14-06-2026"),
    ],
)
def test_transaction_filters_survive_pagination_and_fanout(
    incremental: bool, watermark: object, expected_start: str
) -> None:
    resume_manager = manager()
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/accounts?page=1",
            json=page([{"id": "account-a"}], f"{BASE_URL}/accounts?page=2"),
            complete_qs=True,
        )
        http.get(f"{BASE_URL}/accounts?page=2", json=page([{"id": "account-b"}]), complete_qs=True)
        http.get(
            f"{BASE_URL}/accounts/account-a/transactions?page=1",
            json=page(
                [{"id": "shared-id", "date": "2026-06-10T00:00:00Z"}], f"{BASE_URL}/account-a/transactions?page=2"
            ),
        )
        http.get(
            f"{BASE_URL}/accounts/account-a/transactions?page=2",
            json=page([{"id": "older-id", "date": "2026-06-09T00:00:00Z"}]),
        )
        http.get(
            f"{BASE_URL}/accounts/account-b/transactions?page=1",
            json=page([{"id": "shared-id", "date": "2026-06-11T00:00:00Z"}]),
        )
        response = source(
            "transactions",
            resume_manager,
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )
        result = rows(response)
        assert [(row["account_id"], row["id"]) for row in result] == [
            ("account-a", "shared-id"),
            ("account-a", "older-id"),
            ("account-b", "shared-id"),
        ]
        assert len({tuple(row[key] for key in response.primary_keys or []) for row in result}) == 3
        assert response.sort_mode == "desc"
        assert http.call_count == 5
        for request in http.request_history:
            assert request.headers["mono-sec-key"] == CONFIG.api_key
            assert "x-real-time" not in request.headers
            if "/transactions" in request.path:
                assert request.qs == {
                    "page": request.qs["page"],
                    "start": [expected_start],
                    "end": ["15-06-2026"],
                    "paginate": ["true"],
                    "limit": ["100"],
                }
        checkpoint = resume_manager.save_state.call_args_list[0].args[0]
        assert checkpoint == MonoResumeConfig(
            paginator_state={"completed": [], "current": "accounts/account-a/transactions", "child_state": {"page": 2}},
            start=expected_start,
            end="15-06-2026",
        )
        assert resume_manager.save_state.call_args.args[0].paginator_state == {
            "completed": ["accounts/account-a/transactions", "accounts/account-b/transactions"],
            "current": None,
            "child_state": None,
        }


@time_machine.travel("2026-06-16T12:00:00Z", tick=False)
def test_resumes_child_page_with_original_date_bounds_and_skips_completed_accounts() -> None:
    saved = MonoResumeConfig(
        paginator_state={
            "completed": ["accounts/account-a/transactions"],
            "current": "accounts/account-b/transactions",
            "child_state": {"page": 3},
        },
        start="09-06-2026",
        end="15-06-2026",
    )
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/accounts", json=page([{"id": "account-a"}, {"id": "account-b"}]))
        http.get(
            f"{BASE_URL}/accounts/account-b/transactions?page=3&start=09-06-2026&end=15-06-2026&paginate=true&limit=100",
            json=page([{"id": "transaction-3"}]),
            complete_qs=True,
        )
        assert rows(source("transactions", manager(saved))) == [{"id": "transaction-3", "account_id": "account-b"}]
        assert http.call_count == 2


@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
def test_empty_account_does_not_stop_later_accounts() -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/accounts", json=page([{"id": "account-a"}, {"id": "account-b"}]))
        http.get(f"{BASE_URL}/accounts/account-a/transactions", json=page([]))
        http.get(f"{BASE_URL}/accounts/account-b/transactions", json=page([{"id": "transaction-b"}]))
        assert rows(source("transactions", manager())) == [{"id": "transaction-b", "account_id": "account-b"}]
        assert http.call_count == 3


@pytest.mark.parametrize("next_url", ["?page=1", "?page=0", "?page=no", "?offset=2", "?page=2&page=3"])
def test_invalid_next_page_fails_instead_of_truncating_or_looping(next_url: str) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/customers", json=page([{"id": "customer-1"}], next_url))
        with pytest.raises(ValueError, match="invalid pagination link"):
            rows(source("customers", manager()))
        assert http.call_count == 1


@pytest.mark.parametrize("status,expected", [(200, None), (401, "secret API key"), (403, "denied access")])
@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
def test_credential_probe_maps_auth_errors_and_reads_only_one_page(status: int, expected: str | None) -> None:
    body = (
        page([], f"{BASE_URL}/customers?page=2")
        if status == 200
        else {"status": "failed", "message": "Unauthorized request.", "data": None}
    )
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/customers", status_code=status, json=body)
        valid, error = validate_credentials(CONFIG, "v2", 1)
        assert valid is (status == 200)
        if expected:
            assert expected in (error or "")
        else:
            assert error is None
        assert http.call_count == 1
        assert http.last_request is not None
        assert http.last_request.headers["mono-sec-key"] == CONFIG.api_key


@pytest.mark.parametrize("status", [400, 404])
def test_other_credential_probe_errors_propagate(status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/customers", status_code=status, json={"status": "failed"})
        with pytest.raises(HTTPError):
            validate_credentials(CONFIG, "v2", 1)
        assert http.call_count == 1


@pytest.mark.parametrize("status,expected", [(401, "secret API key"), (403, "denied access")])
def test_sync_auth_errors_match_user_facing_error_mapping(status: int, expected: str) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/accounts", status_code=status, json={"message": "Unauthorized request."})
        with pytest.raises(HTTPError) as error:
            rows(source("accounts", manager()))
        messages = MonoSource().get_non_retryable_errors()
        assert any(pattern in str(error.value) and expected in (message or "") for pattern, message in messages.items())
        assert http.call_count == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_responses_retry_without_advancing_page(status: int) -> None:
    with requests_mock.Mocker() as http, patch.object(RESTClient._send_request.retry, "sleep"):  # type: ignore[attr-defined]
        http.get(
            f"{BASE_URL}/customers?page=1",
            [
                {"status_code": status, "json": {"status": "failed"}, "headers": {"Retry-After": "0"}},
                {"json": page([{"id": "customer-1"}])},
            ],
            complete_qs=True,
        )
        assert rows(source("customers", manager())) == [{"id": "customer-1"}]
        assert http.call_count == 2


@pytest.mark.parametrize(
    "start_date,expected",
    [
        ("invalid", "YYYY-MM-DD"),
        ("2026-02-30", "YYYY-MM-DD"),
        ("20260101", "YYYY-MM-DD"),
        ("2026-06-15", "before today"),
        ("2026-06-16", "before today"),
    ],
)
@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
def test_invalid_start_dates_fail_before_any_request(start_date: str, expected: str) -> None:
    with requests_mock.Mocker() as http:
        valid, error = validate_credentials(MonoSourceConfig(api_key=CONFIG.api_key, start_date=start_date), "v2", 1)
        assert not valid
        assert expected in (error or "")
        assert http.call_count == 0


def test_invalid_watermark_and_unknown_table_fail_before_any_request() -> None:
    with requests_mock.Mocker() as http:
        with pytest.raises(ValueError, match="invalid transaction watermark"):
            source(
                "transactions", manager(), should_use_incremental_field=True, db_incremental_field_last_value="invalid"
            )
        with pytest.raises(UnknownResourceError):
            source("missing", manager())
        assert http.call_count == 0
