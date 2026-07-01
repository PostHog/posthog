from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex import (
    BrexResumeConfig,
    _build_params,
    _build_url,
    _to_rfc3339,
    brex_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import (
    BREX_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)


def _make_manager(resume_state: BrexResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items: list[dict[str, Any]], next_cursor: str | None) -> dict[str, Any]:
    return {"items": items, "next_cursor": next_cursor}


def _response(payload: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = payload
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    return response


class TestToRfc3339:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02", "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
            (1700000000, None),
        ],
    )
    def test_to_rfc3339_values(self, value, expected):
        assert _to_rfc3339(value) == expected


class TestBuildParams:
    def test_always_includes_limit(self):
        params = _build_params(BREX_ENDPOINTS["users"], cursor=None, incremental_value=None)
        assert params == {"limit": 100}

    def test_includes_cursor_when_set(self):
        params = _build_params(BREX_ENDPOINTS["users"], cursor="abc", incremental_value=None)
        assert params["cursor"] == "abc"

    @pytest.mark.parametrize(
        "endpoint, expected_param",
        [
            ("card_transactions", "posted_at_start"),
            ("cash_transactions", "posted_at_start"),
            ("expenses", "updated_at_start"),
        ],
    )
    def test_incremental_param_included_for_incremental_endpoints(self, endpoint, expected_param):
        params = _build_params(BREX_ENDPOINTS[endpoint], cursor=None, incremental_value="2024-01-02T00:00:00Z")
        assert params[expected_param] == "2024-01-02T00:00:00Z"

    @pytest.mark.parametrize("endpoint", ["users", "departments", "locations", "vendors", "budgets"])
    def test_incremental_value_ignored_for_full_refresh_endpoints(self, endpoint):
        params = _build_params(BREX_ENDPOINTS[endpoint], cursor=None, incremental_value="2024-01-02T00:00:00Z")
        assert params == {"limit": 100}

    def test_incremental_param_omitted_without_value(self):
        params = _build_params(BREX_ENDPOINTS["expenses"], cursor=None, incremental_value=None)
        assert "updated_at_start" not in params


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/v2/users", {}) == "https://api.brex.com/v2/users"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("/v1/expenses", {"limit": 100, "cursor": None, "updated_at_start": "2024-01-02T00:00:00Z"})
        assert url == "https://api.brex.com/v1/expenses?limit=100&updated_at_start=2024-01-02T00%3A00%3A00Z"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # A valid token without the Team scope returns 403 — accepted at source-create.
            (403, True),
            (401, False),
            (500, False),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)

        assert validate_credentials("bxt_token") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("bxt_token") is False

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_validate_credentials_sends_bearer_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("bxt_token")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer bxt_token"


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_paginates_via_next_cursor(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "u1"}, {"id": "u2"}], "cursor-2")),
            _response(_page([{"id": "u3"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("bxt_token", "users", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["u1", "u2", "u3"]
        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert first_url == "https://api.brex.com/v2/users?limit=100"
        assert "cursor=cursor-2" in second_url
        # State is saved only while a next page exists, after the batch has been yielded.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BrexResumeConfig(cursor="cursor-2")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _response(_page([{"id": "u9"}], None))

        manager = _make_manager(BrexResumeConfig(cursor="cursor-5"))
        list(get_rows("bxt_token", "users", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "cursor=cursor-5" in first_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response(_page([], None))

        manager = _make_manager()
        batches = list(get_rows("bxt_token", "expenses", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_incremental_run_passes_server_side_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response(_page([{"id": "e1"}], None))

        manager = _make_manager()
        list(
            get_rows(
                "bxt_token",
                "expenses",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert "updated_at_start=2024-01-02T00%3A00%3A00Z" in url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_full_refresh_run_has_no_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response(_page([{"id": "e1"}], None))

        manager = _make_manager()
        list(get_rows("bxt_token", "expenses", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert "updated_at_start" not in url

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.time")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_429_honors_retry_after_then_retries(self, mock_session, mock_time, mock_nap):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=429, headers={"Retry-After": "7"}),
            _response(_page([{"id": "u1"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("bxt_token", "users", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["u1"]
        mock_time.sleep.assert_called_once_with(7)

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.time")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_429_with_unparseable_retry_after_still_retries(self, mock_session, mock_time, mock_nap):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=429, headers={"Retry-After": "not-a-number"}),
            _response(_page([{"id": "u1"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("bxt_token", "users", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["u1"]
        mock_time.sleep.assert_not_called()

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_5xx_is_retried(self, mock_session, mock_nap):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=502),
            _response(_page([{"id": "u1"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("bxt_token", "users", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["u1"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_4xx_raises_immediately(self, mock_session):
        response = _response({}, status_code=401)
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized for url: https://api.brex.com/v2/users", response=response
        )
        response.text = "unauthorized"
        mock_session.return_value.get.return_value = response

        manager = _make_manager()
        with pytest.raises(requests.HTTPError):
            list(get_rows("bxt_token", "users", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 1


class TestGetRowsCashFanOut:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_fans_out_over_cash_accounts_and_injects_account_id(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
            _response(_page([{"id": "tx_1", "posted_at_date": "2024-01-01"}], None)),
            _response(_page([{"id": "tx_2", "posted_at_date": "2024-01-02"}], None)),
        ]

        manager = _make_manager()
        batches = list(get_rows("bxt_token", "cash_transactions", mock.MagicMock(), manager))

        rows = [item for batch in batches for item in batch]
        assert [(row["id"], row["account_id"]) for row in rows] == [("tx_1", "acc_1"), ("tx_2", "acc_2")]

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[0] == "https://api.brex.com/v2/accounts/cash?limit=100"
        assert urls[1].startswith("https://api.brex.com/v2/transactions/cash/acc_1")
        assert urls[2].startswith("https://api.brex.com/v2/transactions/cash/acc_2")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_saves_completed_accounts_between_accounts(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
            _response(_page([{"id": "tx_1"}], "cursor-a")),
            _response(_page([{"id": "tx_2"}], None)),
            _response(_page([{"id": "tx_3"}], None)),
        ]

        manager = _make_manager()
        list(get_rows("bxt_token", "cash_transactions", mock.MagicMock(), manager))

        saved_states = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved_states == [
            BrexResumeConfig(cursor="cursor-a", account_id="acc_1", completed_account_ids=[]),
            BrexResumeConfig(cursor=None, account_id=None, completed_account_ids=["acc_1"]),
            BrexResumeConfig(cursor=None, account_id=None, completed_account_ids=["acc_1", "acc_2"]),
        ]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_resume_skips_completed_accounts_and_uses_cursor(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
            _response(_page([{"id": "tx_9"}], None)),
        ]

        manager = _make_manager(
            BrexResumeConfig(cursor="cursor-mid", account_id="acc_2", completed_account_ids=["acc_1"])
        )
        batches = list(get_rows("bxt_token", "cash_transactions", mock.MagicMock(), manager))

        rows = [item for batch in batches for item in batch]
        assert [(row["id"], row["account_id"]) for row in rows] == [("tx_9", "acc_2")]

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert len(urls) == 2
        assert "transactions/cash/acc_2" in urls[1]
        assert "cursor=cursor-mid" in urls[1]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_resume_cursor_not_applied_to_other_accounts(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "acc_1"}], None)),
            _response(_page([{"id": "tx_1"}], None)),
        ]

        manager = _make_manager(BrexResumeConfig(cursor="cursor-mid", account_id="acc_gone", completed_account_ids=[]))
        list(get_rows("bxt_token", "cash_transactions", mock.MagicMock(), manager))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "cursor=" not in urls[1]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_paginates_cash_account_listing(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "acc_1"}], "acc-cursor-2")),
            _response(_page([{"id": "acc_2"}], None)),
            _response(_page([], None)),
            _response(_page([], None)),
        ]

        manager = _make_manager()
        list(get_rows("bxt_token", "cash_transactions", mock.MagicMock(), manager))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "accounts/cash" in urls[0]
        assert "cursor=acc-cursor-2" in urls[1]
        assert "transactions/cash/acc_1" in urls[2]
        assert "transactions/cash/acc_2" in urls[3]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session")
    def test_incremental_filter_applied_per_account(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "acc_1"}], None)),
            _response(_page([{"id": "tx_1"}], None)),
        ]

        manager = _make_manager()
        list(
            get_rows(
                "bxt_token",
                "cash_transactions",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-02",
            )
        )

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        # Account listing carries no filter; the per-account transaction call does.
        assert "posted_at_start" not in urls[0]
        assert "posted_at_start=2024-01-02T00%3A00%3A00Z" in urls[1]


class TestBrexSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BREX_ENDPOINTS[endpoint]
        response = brex_source("bxt_token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.incremental_fields:
            assert response.sort_mode == "desc"
        else:
            assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_cash_transactions_use_composite_primary_key(self):
        response = brex_source("bxt_token", "cash_transactions", mock.MagicMock(), _make_manager())
        assert response.primary_keys == ["account_id", "id"]

    def test_budgets_primary_key_is_budget_id(self):
        response = brex_source("bxt_token", "budgets", mock.MagicMock(), _make_manager())
        assert response.primary_keys == ["budget_id"]

    @pytest.mark.parametrize("config", list(BREX_ENDPOINTS.values()))
    def test_partition_keys_are_stable_posted_dates(self, config):
        if config.partition_key:
            assert config.partition_key == "posted_at_date"

    def test_incremental_fields_only_declared_for_filterable_endpoints(self):
        assert set(INCREMENTAL_FIELDS.keys()) == {"card_transactions", "cash_transactions", "expenses"}
