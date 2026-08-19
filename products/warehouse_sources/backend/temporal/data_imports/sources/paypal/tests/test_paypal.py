from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.paypal import (
    PayPalResumeConfig,
    PayPalRetryableError,
    _base_url,
    _date_windows,
    _dispute_start,
    _flatten_transaction,
    _format_dispute_datetime,
    _format_reporting_datetime,
    _has_more_pages,
    _next_page_token,
    _to_datetime,
    _transaction_start,
    check_endpoint_permissions,
    get_rows,
    paypal_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.settings import (
    DISPUTE_HISTORY_DAYS,
    ENDPOINTS,
    PAYPAL_ENDPOINTS,
    TRANSACTION_HISTORY_DAYS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.paypal.paypal"

_NOW = datetime(2024, 6, 30, 12, 0, 0, tzinfo=UTC)


class FakeResumeManager(ResumableSourceManager[PayPalResumeConfig]):
    """Stand-in for the Redis-backed manager that records everything it is asked to persist."""

    def __init__(self, state: Optional[PayPalResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[PayPalResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[PayPalResumeConfig]:
        return self.state

    def save_state(self, data: PayPalResumeConfig) -> None:
        self.saved.append(data)


def _response(body: dict[str, Any], status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status
    resp.ok = status < 400
    return resp


def _token_response() -> mock.MagicMock:
    return _response({"access_token": "minted-token", "expires_in": 32400})


def _collect(
    mock_session: mock.MagicMock,
    endpoint: str,
    manager: FakeResumeManager,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[list[dict[str, Any]]]:
    return list(
        get_rows(
            "live",
            "cid",
            "secret",
            endpoint,
            mock.MagicMock(),
            manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
    )


class TestPayPalTransport:
    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("live", "https://api-m.paypal.com"),
            ("sandbox", "https://api-m.sandbox.paypal.com"),
        ],
    )
    def test_known_environments_resolve_to_paypal_hosts(self, environment: str, expected: str) -> None:
        assert _base_url(environment) == expected

    def test_unknown_environment_raises(self) -> None:
        with pytest.raises(ValueError):
            _base_url("production")

    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2024, 5, 1, 6, 30, tzinfo=UTC), datetime(2024, 5, 1, 6, 30, tzinfo=UTC)),
            (datetime(2024, 5, 1, 6, 30), datetime(2024, 5, 1, 6, 30, tzinfo=UTC)),
            (date(2024, 5, 1), datetime(2024, 5, 1, tzinfo=UTC)),
            ("2024-05-01T06:30:00Z", datetime(2024, 5, 1, 6, 30, tzinfo=UTC)),
            ("2024-05-01", datetime(2024, 5, 1, tzinfo=UTC)),
            ("not a date", None),
        ],
    )
    def test_watermark_coercion(self, value: Any, expected: Optional[datetime]) -> None:
        assert _to_datetime(value) == expected

    def test_reporting_and_dispute_datetime_formats_differ(self) -> None:
        value = datetime(2024, 5, 1, 6, 30, 15, tzinfo=UTC)
        assert _format_reporting_datetime(value) == "2024-05-01T06:30:15-0000"
        assert _format_dispute_datetime(value) == "2024-05-01T06:30:15.000Z"

    @pytest.mark.parametrize(
        "links, expected",
        [
            ([{"rel": "next", "href": "https://api-m.paypal.com/v1/customer/disputes?next_page_token=abc"}], "abc"),
            ([{"rel": "self", "href": "https://api-m.paypal.com/v1/customer/disputes?next_page_token=abc"}], None),
            ([{"rel": "next", "href": "https://api-m.paypal.com/v1/customer/disputes"}], None),
            ([{"rel": "next"}], None),
            ([], None),
            (None, None),
        ],
    )
    def test_next_page_token_extraction(self, links: Any, expected: Optional[str]) -> None:
        assert _next_page_token(links) == expected

    def test_flatten_transaction_hoists_ids_and_dates(self) -> None:
        row = _flatten_transaction(
            {
                "transaction_info": {
                    "transaction_id": "T1",
                    "transaction_initiation_date": "2024-05-01T00:00:00+0000",
                    "transaction_updated_date": "2024-05-02T00:00:00+0000",
                },
                "payer_info": {"email_address": "a@b.com"},
            }
        )

        assert row["transaction_id"] == "T1"
        assert row["transaction_initiation_date"] == "2024-05-01T00:00:00+0000"
        assert row["transaction_updated_date"] == "2024-05-02T00:00:00+0000"
        assert row["payer_info"] == {"email_address": "a@b.com"}

    def test_flatten_transaction_tolerates_missing_transaction_info(self) -> None:
        assert _flatten_transaction({})["transaction_id"] is None

    def test_date_windows_tile_the_range_without_gaps_or_overlap(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 20, tzinfo=UTC)

        windows = _date_windows(start, end, 7)

        assert windows[0].start == start
        assert windows[-1].end == end
        assert all(windows[i].end == windows[i + 1].start for i in range(len(windows) - 1))
        assert all((w.end - w.start) <= timedelta(days=7) for w in windows)

    @pytest.mark.parametrize("window_days", [1, 7, 31])
    def test_date_windows_never_exceed_the_paypal_window_cap(self, window_days: int) -> None:
        windows = _date_windows(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC), window_days)
        assert windows
        assert all((w.end - w.start) <= timedelta(days=31) for w in windows)

    def test_date_windows_empty_when_start_is_not_before_end(self) -> None:
        moment = datetime(2024, 1, 1, tzinfo=UTC)
        assert _date_windows(moment, moment, 7) == []

    def test_transaction_start_defaults_to_the_three_year_retention_floor(self) -> None:
        start = _transaction_start(None, _NOW)

        assert start == (_NOW - timedelta(days=TRANSACTION_HISTORY_DAYS)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def test_transaction_start_uses_the_watermark_when_it_is_within_retention(self) -> None:
        assert _transaction_start("2024-05-01T00:00:00Z", _NOW) == datetime(2024, 5, 1, tzinfo=UTC)

    def test_transaction_start_clamps_a_watermark_older_than_retention(self) -> None:
        assert _transaction_start("2010-01-01T00:00:00Z", _NOW) == _NOW - timedelta(days=TRANSACTION_HISTORY_DAYS)

    def test_dispute_start_is_none_for_a_full_refresh(self) -> None:
        assert _dispute_start(None, _NOW) is None

    def test_dispute_start_uses_the_watermark_when_within_180_days(self) -> None:
        assert _dispute_start("2024-05-01T06:30:00Z", _NOW) == datetime(2024, 5, 1, 6, 30, tzinfo=UTC)

    def test_dispute_start_clamps_a_watermark_older_than_180_days(self) -> None:
        assert _dispute_start("2023-01-01T00:00:00Z", _NOW) == _NOW - timedelta(days=DISPUTE_HISTORY_DAYS)

    @pytest.mark.parametrize(
        "items, total_pages, page, page_size, expected",
        [
            ([], 5, 1, 100, False),
            ([{"id": 1}], 3, 1, 100, True),
            ([{"id": 1}], 3, 3, 100, False),
            ([{"id": 1}], None, 1, 1, True),
            ([{"id": 1}], None, 1, 100, False),
        ],
    )
    def test_page_termination(
        self, items: list[Any], total_pages: Any, page: int, page_size: int, expected: bool
    ) -> None:
        assert _has_more_pages(items, total_pages, page, page_size) is expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [(200, True), (400, False), (401, False), (500, False)],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session: mock.MagicMock, status: int, expected_valid: bool) -> None:
        mock_session.return_value.post.return_value = _response({}, status=status)

        is_valid, message = validate_credentials("live", "cid", "secret")

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_posts_client_credentials_grant_with_basic_auth(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _response({}, status=200)

        validate_credentials("sandbox", "cid", "secret")

        call = mock_session.return_value.post.call_args
        assert call.args[0] == "https://api-m.sandbox.paypal.com/v1/oauth2/token"
        assert call.kwargs["data"] == {"grant_type": "client_credentials"}
        assert call.kwargs["auth"] == ("cid", "secret")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_failure_is_reported_not_raised(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.side_effect = Exception("boom")

        is_valid, message = validate_credentials("live", "cid", "secret")

        assert is_valid is False
        assert message is not None

    def test_unknown_environment_is_rejected_without_a_request(self) -> None:
        is_valid, message = validate_credentials("prod", "cid", "secret")

        assert is_valid is False
        assert message is not None


@mock.patch(f"{_MODULE}.make_tracked_session")
class TestEndpointPermissions:
    def test_a_403_reports_the_feature_the_app_must_enable(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({}, status=403)

        result = check_endpoint_permissions("live", "cid", "secret", ["transactions"])

        assert result["transactions"] is not None
        assert "Transaction Search" in result["transactions"]

    def test_a_reachable_endpoint_reports_no_error(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"items": []}, status=200)

        assert check_endpoint_permissions("live", "cid", "secret", ["disputes"]) == {"disputes": None}

    @pytest.mark.parametrize("status", [429, 500])
    def test_a_transient_failure_is_not_reported_as_a_missing_feature(
        self, mock_session: mock.MagicMock, status: int
    ) -> None:
        # A throttle or 5xx must not masquerade as a denied table, or setup would wrongly disable it.
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({}, status=status)

        assert check_endpoint_permissions("live", "cid", "secret", ["invoices"]) == {"invoices": None}

    def test_a_token_mint_failure_never_blocks_discovery(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.side_effect = Exception("boom")

        result = check_endpoint_permissions("live", "cid", "secret", ["transactions", "disputes"])

        assert result == {"transactions": None, "disputes": None}


@mock.patch(f"{_MODULE}._now", return_value=_NOW)
@mock.patch(f"{_MODULE}.make_tracked_session")
class TestGetRows:
    def test_balances_folds_account_and_snapshot_time_into_each_row(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response(
            {
                "account_id": "ACC1",
                "as_of_time": "2024-06-30T12:00:00Z",
                "balances": [{"currency": "USD"}, {"currency": "GBP"}],
            }
        )

        batches = _collect(mock_session, "balances", FakeResumeManager())

        assert batches == [
            [
                {"currency": "USD", "account_id": "ACC1", "as_of_time": "2024-06-30T12:00:00Z"},
                {"currency": "GBP", "account_id": "ACC1", "as_of_time": "2024-06-30T12:00:00Z"},
            ]
        ]
        assert mock_session.return_value.get.call_args.kwargs["params"] == {"currency_code": "ALL"}

    def test_bearer_token_is_minted_once_and_sent_on_api_calls(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"balances": []})

        _collect(mock_session, "balances", FakeResumeManager())

        assert mock_session.return_value.post.call_count == 1
        assert mock_session.return_value.get.call_args.kwargs["headers"] == {"Authorization": "Bearer minted-token"}

    def test_expired_token_is_reminted_once_and_the_call_retried(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response({}, status=401),
            _response({"balances": [{"currency": "USD"}]}),
        ]

        batches = _collect(mock_session, "balances", FakeResumeManager())

        assert len(batches) == 1
        # One mint up front plus one re-mint after the 401.
        assert mock_session.return_value.post.call_count == 2

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_throttles_and_server_errors_are_retryable(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock, status: int
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({}, status=status)

        with mock.patch(f"{_MODULE}.MAX_RETRY_ATTEMPTS", 1), pytest.raises(PayPalRetryableError):
            _collect(mock_session, "balances", FakeResumeManager())

    def test_transactions_slice_the_range_into_windows_within_paypals_cap(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"transaction_details": [], "total_pages": 0})

        _collect(
            mock_session,
            "transactions",
            FakeResumeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-01T00:00:00Z",
        )

        params = [call.kwargs["params"] for call in mock_session.return_value.get.call_args_list]
        # 2024-06-01 -> 2024-06-30 12:00 in 7-day slices: 4 full weeks plus the remainder.
        assert len(params) == 5
        assert params[0]["start_date"] == "2024-06-01T00:00:00-0000"
        assert params[0]["end_date"] == "2024-06-08T00:00:00-0000"
        assert params[-1]["end_date"] == "2024-06-30T12:00:00-0000"
        assert all(p["page"] == 1 and p["page_size"] == 500 and p["fields"] == "all" for p in params)

    def test_transactions_page_within_a_window_and_checkpoint_after_each_page(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        page = [{"transaction_info": {"transaction_id": "T1"}}]
        mock_session.return_value.get.side_effect = [
            _response({"transaction_details": page, "total_pages": 2}),
            _response({"transaction_details": page, "total_pages": 2}),
        ]

        manager = FakeResumeManager()
        batches = _collect(
            mock_session,
            "transactions",
            manager,
            should_use_incremental_field=True,
            # A single window: less than one slice wide.
            db_incremental_field_last_value="2024-06-28T00:00:00Z",
        )

        assert len(batches) == 2
        assert [row["transaction_id"] for batch in batches for row in batch] == ["T1", "T1"]
        # Checkpointed onto page 2 of the window we were walking; no window follows it.
        assert manager.saved == [PayPalResumeConfig(window_start="2024-06-28T00:00:00+00:00", page=2)]

    def test_transactions_checkpoint_the_next_window_once_one_is_finished(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response(
            {"transaction_details": [{"transaction_info": {"transaction_id": "T1"}}], "total_pages": 1}
        )

        manager = FakeResumeManager()
        _collect(
            mock_session,
            "transactions",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-16T00:00:00Z",
        )

        # 2024-06-16 -> 2024-06-30 12:00 is three windows, so two hand-offs to the next window.
        assert [state.window_start for state in manager.saved] == [
            "2024-06-23T00:00:00+00:00",
            "2024-06-30T00:00:00+00:00",
        ]
        assert all(state.page == 1 for state in manager.saved)

    def test_transactions_resume_from_the_saved_window_and_page(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"transaction_details": [], "total_pages": 0})

        manager = FakeResumeManager(PayPalResumeConfig(window_start="2024-06-23T00:00:00+00:00", page=4))
        _collect(
            mock_session,
            "transactions",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-02T00:00:00Z",
        )

        params = [call.kwargs["params"] for call in mock_session.return_value.get.call_args_list]
        # The three windows before the checkpoint are skipped; the checkpointed one restarts on
        # page 4, and the remaining window after it is walked from page 1.
        assert [(p["start_date"], p["page"]) for p in params] == [
            ("2024-06-23T00:00:00-0000", 4),
            ("2024-06-30T00:00:00-0000", 1),
        ]

    def test_transactions_ignore_stale_resume_state_that_matches_no_window(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"transaction_details": [], "total_pages": 0})

        manager = FakeResumeManager(PayPalResumeConfig(window_start="2019-01-01T00:00:00+00:00", page=9))
        _collect(
            mock_session,
            "transactions",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-24T00:00:00Z",
        )

        params = [call.kwargs["params"] for call in mock_session.return_value.get.call_args_list]
        assert params[0]["start_date"] == "2024-06-24T00:00:00-0000"
        assert params[0]["page"] == 1

    def test_full_refresh_transactions_start_at_the_retention_floor(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"transaction_details": [], "total_pages": 0})

        _collect(mock_session, "transactions", FakeResumeManager(), db_incremental_field_last_value="2024-06-01Z")

        first_params = mock_session.return_value.get.call_args_list[0].kwargs["params"]
        expected = (_NOW - timedelta(days=TRANSACTION_HISTORY_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
        assert first_params["start_date"] == _format_reporting_datetime(expected)

    def test_disputes_follow_the_next_page_token_until_it_runs_out(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response(
                {
                    "items": [{"dispute_id": "D1"}],
                    "links": [{"rel": "next", "href": "https://api-m.paypal.com/x?next_page_token=tok2"}],
                }
            ),
            _response({"items": [{"dispute_id": "D2"}], "links": [{"rel": "self", "href": "https://x"}]}),
        ]

        manager = FakeResumeManager()
        batches = _collect(mock_session, "disputes", manager)

        assert batches == [[{"dispute_id": "D1"}], [{"dispute_id": "D2"}]]
        assert manager.saved == [PayPalResumeConfig(next_page_token="tok2")]
        tokens = [call.kwargs["params"].get("next_page_token") for call in mock_session.return_value.get.call_args_list]
        assert tokens == [None, "tok2"]

    def test_disputes_push_the_watermark_into_the_update_time_after_filter(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"items": [], "links": []})

        _collect(
            mock_session,
            "disputes",
            FakeResumeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01T06:30:00Z",
        )

        params = mock_session.return_value.get.call_args.kwargs["params"]
        # Incremental disputes filter on update time so status changes on old disputes are re-fetched.
        assert params["update_time_after"] == "2024-05-01T06:30:00.000Z"
        assert "start_time" not in params
        assert params["page_size"] == 50

    def test_disputes_full_refresh_sends_no_update_time_filter(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"items": [], "links": []})

        _collect(
            mock_session,
            "disputes",
            FakeResumeManager(),
            should_use_incremental_field=False,
            db_incremental_field_last_value="2024-05-01T06:30:00Z",
        )

        assert "update_time_after" not in mock_session.return_value.get.call_args.kwargs["params"]

    def test_disputes_resume_from_the_saved_page_token(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"items": [], "links": []})

        _collect(mock_session, "disputes", FakeResumeManager(PayPalResumeConfig(next_page_token="tok9")))

        assert mock_session.return_value.get.call_args.kwargs["params"]["next_page_token"] == "tok9"

    @pytest.mark.parametrize("endpoint", ["invoices", "plans", "products"])
    def test_page_numbered_listings_walk_to_total_pages(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock, endpoint: str
    ) -> None:
        selector = PAYPAL_ENDPOINTS[endpoint].data_selector
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response({selector: [{"id": "1"}], "total_pages": 2}),
            _response({selector: [{"id": "2"}], "total_pages": 2}),
        ]

        manager = FakeResumeManager()
        batches = _collect(mock_session, endpoint, manager)

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert manager.saved == [PayPalResumeConfig(page=2)]
        pages = [call.kwargs["params"]["page"] for call in mock_session.return_value.get.call_args_list]
        assert pages == [1, 2]
        assert mock_session.return_value.get.call_args.kwargs["params"]["total_required"] == "true"

    def test_page_numbered_listings_stop_on_a_short_page_when_total_pages_is_absent(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"plans": [{"id": "1"}]})

        batches = _collect(mock_session, "plans", FakeResumeManager())

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.get.call_count == 1

    def test_page_numbered_listings_resume_from_the_saved_page(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"items": [], "total_pages": 7})

        _collect(mock_session, "invoices", FakeResumeManager(PayPalResumeConfig(page=5)))

        assert mock_session.return_value.get.call_args.kwargs["params"]["page"] == 5

    def test_empty_listing_yields_nothing_and_saves_no_state(
        self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock
    ) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"items": [], "total_pages": 3})

        manager = FakeResumeManager()
        assert _collect(mock_session, "invoices", manager) == []
        assert manager.saved == []


class TestPayPalSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config = PAYPAL_ENDPOINTS[endpoint]

        response = paypal_source("live", "cid", "secret", endpoint, mock.MagicMock(), FakeResumeManager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == config.sort_mode
        if config.partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]

    @mock.patch(f"{_MODULE}._now", return_value=_NOW)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_items_is_lazy_until_iterated(self, mock_session: mock.MagicMock, _mock_now: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"balances": []})

        response = paypal_source("live", "cid", "secret", "balances", mock.MagicMock(), FakeResumeManager())

        assert mock_session.return_value.post.call_count == 0
        list(cast("Iterable[Any]", response.items()))
        assert mock_session.return_value.post.call_count == 1
