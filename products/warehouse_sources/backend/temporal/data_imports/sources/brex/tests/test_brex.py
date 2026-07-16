import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex import (
    BrexResumeConfig,
    _to_rfc3339,
    brex_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import (
    BREX_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the brex module.
BREX_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex.make_tracked_session"

CASH_TX_PATH = BREX_ENDPOINTS["cash_transactions"].path


def _response(
    payload: dict[str, Any],
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    resp.url = "https://api.brex.com/test"
    if headers:
        resp.headers.update(headers)
    return resp


def _page(items: list[dict[str, Any]], next_cursor: str | None) -> dict[str, Any]:
    return {"items": items, "next_cursor": next_cursor}


def _make_manager(resume_state: BrexResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's url + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return brex_source(
        "bxt_token",
        endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
    @mock.patch(BREX_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)

        assert validate_credentials("bxt_token") is expected

    @mock.patch(BREX_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("bxt_token") is False

    @mock.patch(BREX_SESSION_PATCH)
    def test_validate_credentials_sends_bearer_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("bxt_token")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer bxt_token"


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_next_cursor(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "u1"}, {"id": "u2"}], "cursor-2")),
                _response(_page([{"id": "u3"}], None)),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [row["id"] for row in rows] == ["u1", "u2", "u3"]
        assert snapshots[0]["url"] == "https://api.brex.com/v2/users"
        assert snapshots[0]["params"] == {"limit": 100}
        assert snapshots[1]["params"] == {"limit": 100, "cursor": "cursor-2"}
        # State is saved only while a next page exists, after the batch has been yielded.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BrexResumeConfig(cursor="cursor-2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page([{"id": "u9"}], None))])

        manager = _make_manager(BrexResumeConfig(cursor="cursor-5"))
        _rows(_source("users", manager))

        assert snapshots[0]["params"]["cursor"] == "cursor-5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(_page([], None))])

        manager = _make_manager()
        rows = _rows(_source("expenses", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_run_passes_server_side_filter(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page([{"id": "e1"}], None))])

        manager = _make_manager()
        _rows(
            _source(
                "expenses",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["updated_at_start"] == "2024-01-02T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_resent_on_every_page(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "e1"}], "cursor-2")),
                _response(_page([{"id": "e2"}], None)),
            ],
        )

        manager = _make_manager()
        _rows(
            _source(
                "expenses",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert snapshots[1]["params"]["updated_at_start"] == "2024-01-02T00:00:00Z"
        assert snapshots[1]["params"]["cursor"] == "cursor-2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_param_omitted_without_value(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page([{"id": "e1"}], None))])

        manager = _make_manager()
        _rows(_source("expenses", manager, should_use_incremental_field=True))

        assert "updated_at_start" not in snapshots[0]["params"]

    @pytest.mark.parametrize("endpoint", ["users", "departments", "locations", "vendors", "budgets"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_value_ignored_for_full_refresh_endpoints(self, MockSession, endpoint):
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page([{"id": "x"}], None))])

        manager = _make_manager()
        _rows(
            _source(
                endpoint,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-02",
            )
        )

        assert snapshots[0]["params"] == {"limit": 100}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_run_has_no_filter(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page([{"id": "e1"}], None))])

        manager = _make_manager()
        _rows(_source("expenses", manager))

        assert "updated_at_start" not in snapshots[0]["params"]

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_honors_retry_after_then_retries(self, MockSession, mock_nap):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status_code=429, headers={"Retry-After": "7"}),
                _response(_page([{"id": "u1"}], None)),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [row["id"] for row in rows] == ["u1"]
        mock_nap.assert_called_once_with(7.0)

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_with_unparseable_retry_after_still_retries(self, MockSession, mock_nap):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status_code=429, headers={"Retry-After": "not-a-number"}),
                _response(_page([{"id": "u1"}], None)),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [row["id"] for row in rows] == ["u1"]
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_5xx_is_retried(self, MockSession, mock_nap):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status_code=502),
                _response(_page([{"id": "u1"}], None)),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [row["id"] for row in rows] == ["u1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_4xx_raises_immediately(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=401)])

        manager = _make_manager()
        with pytest.raises(requests.HTTPError):
            _rows(_source("users", manager))

        assert session.send.call_count == 1


class TestGetRowsCashFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_cash_accounts_and_injects_account_id(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
                _response(_page([{"id": "tx_1", "posted_at_date": "2024-01-01"}], None)),
                _response(_page([{"id": "tx_2", "posted_at_date": "2024-01-02"}], None)),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("cash_transactions", manager))

        assert [(row["id"], row["account_id"]) for row in rows] == [("tx_1", "acc_1"), ("tx_2", "acc_2")]
        # The framework's include_from_parent key is renamed away — rows keep their old shape.
        assert all("_cash_accounts_id" not in row for row in rows)

        urls = [snapshot["url"] for snapshot in snapshots]
        assert urls[0] == "https://api.brex.com/v2/accounts/cash"
        assert snapshots[0]["params"] == {"limit": 100}
        assert urls[1] == "https://api.brex.com/v2/transactions/cash/acc_1"
        assert urls[2] == "https://api.brex.com/v2/transactions/cash/acc_2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_fanout_checkpoints_between_accounts(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
                _response(_page([{"id": "tx_1"}], "cursor-a")),
                _response(_page([{"id": "tx_2"}], None)),
                _response(_page([{"id": "tx_3"}], None)),
            ],
        )

        manager = _make_manager()
        _rows(_source("cash_transactions", manager))

        saved_states = [call.args[0].fanout_state for call in manager.save_state.call_args_list]
        acc_1_path = CASH_TX_PATH.format(account_id="acc_1")
        # Mid-account checkpoint carries the account's cursor; completing an account moves it
        # into the completed list.
        assert {"completed": [], "current": acc_1_path, "child_state": {"cursor": "cursor-a"}} in saved_states
        assert saved_states[-1]["completed"] == [
            acc_1_path,
            CASH_TX_PATH.format(account_id="acc_2"),
        ]
        assert saved_states[-1]["current"] is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_accounts_and_uses_cursor(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
                _response(_page([{"id": "tx_9"}], None)),
            ],
        )

        manager = _make_manager(
            BrexResumeConfig(
                fanout_state={
                    "completed": [CASH_TX_PATH.format(account_id="acc_1")],
                    "current": CASH_TX_PATH.format(account_id="acc_2"),
                    "child_state": {"cursor": "cursor-mid"},
                }
            )
        )
        rows = _rows(_source("cash_transactions", manager))

        assert [(row["id"], row["account_id"]) for row in rows] == [("tx_9", "acc_2")]
        assert len(snapshots) == 2
        assert snapshots[1]["url"].endswith("/transactions/cash/acc_2")
        assert snapshots[1]["params"]["cursor"] == "cursor-mid"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_translates_pre_framework_state(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
                _response(_page([{"id": "tx_9"}], None)),
            ],
        )

        manager = _make_manager(
            BrexResumeConfig(cursor="cursor-mid", account_id="acc_2", completed_account_ids=["acc_1"])
        )
        rows = _rows(_source("cash_transactions", manager))

        assert [(row["id"], row["account_id"]) for row in rows] == [("tx_9", "acc_2")]
        assert len(snapshots) == 2
        assert snapshots[1]["url"].endswith("/transactions/cash/acc_2")
        assert snapshots[1]["params"]["cursor"] == "cursor-mid"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_cursor_not_applied_to_other_accounts(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "acc_1"}], None)),
                _response(_page([{"id": "tx_1"}], None)),
            ],
        )

        manager = _make_manager(BrexResumeConfig(cursor="cursor-mid", account_id="acc_gone", completed_account_ids=[]))
        _rows(_source("cash_transactions", manager))

        assert "cursor" not in snapshots[1]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_cash_account_listing(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "acc_1"}], "acc-cursor-2")),
                _response(_page([{"id": "tx_1"}], None)),
                _response(_page([{"id": "acc_2"}], None)),
                _response(_page([{"id": "tx_2"}], None)),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("cash_transactions", manager))

        assert [(row["id"], row["account_id"]) for row in rows] == [("tx_1", "acc_1"), ("tx_2", "acc_2")]
        # Parent pages are consumed lazily: accounts page 1, its transactions, accounts page 2, ...
        assert "accounts/cash" in snapshots[0]["url"]
        assert "transactions/cash/acc_1" in snapshots[1]["url"]
        assert "accounts/cash" in snapshots[2]["url"]
        assert snapshots[2]["params"]["cursor"] == "acc-cursor-2"
        assert "transactions/cash/acc_2" in snapshots[3]["url"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_applied_per_account(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "acc_1"}], None)),
                _response(_page([{"id": "tx_1"}], None)),
            ],
        )

        manager = _make_manager()
        _rows(
            _source(
                "cash_transactions",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-02",
            )
        )

        # Account listing carries no filter; the per-account transaction call does.
        assert "posted_at_start" not in snapshots[0]["params"]
        assert snapshots[1]["params"]["posted_at_start"] == "2024-01-02T00:00:00Z"


@mock.patch(CLIENT_SESSION_PATCH)
class TestBrexSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = BREX_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

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

    def test_cash_transactions_use_composite_primary_key(self, MockSession):
        response = _source("cash_transactions", _make_manager())
        assert response.primary_keys == ["account_id", "id"]

    def test_budgets_primary_key_is_budget_id(self, MockSession):
        response = _source("budgets", _make_manager())
        assert response.primary_keys == ["budget_id"]

    @pytest.mark.parametrize("config", list(BREX_ENDPOINTS.values()))
    def test_partition_keys_are_stable_posted_dates(self, MockSession, config):
        if config.partition_key:
            assert config.partition_key == "posted_at_date"

    def test_incremental_fields_only_declared_for_filterable_endpoints(self, MockSession):
        assert set(INCREMENTAL_FIELDS.keys()) == {"card_transactions", "cash_transactions", "expenses"}
