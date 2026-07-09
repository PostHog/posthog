from datetime import UTC, datetime
from typing import Any, Optional

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.awin import awin
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.awin import (
    AwinResumeConfig,
    _build_window_params,
    _discover_publisher_ids,
    _iter_windows,
    _rows_from_response,
    _to_datetime,
    _windows_for_account,
    awin_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.settings import AWIN_ENDPOINTS


def _counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


class FakeResumableManager:
    """Minimal stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, state: Optional[AwinResumeConfig] = None):
        self.state = state
        self.saved: list[AwinResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[AwinResumeConfig]:
        return self.state

    def save_state(self, data: AwinResumeConfig) -> None:
        self.saved.append(data)


class TestIterWindows:
    def test_range_shorter_than_max_is_single_window(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 10, tzinfo=UTC)
        windows = list(_iter_windows(start, end, max_days=30))
        assert windows == [(start, end)]

    def test_range_is_chunked_and_ascending_and_contiguous(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 3, 15, tzinfo=UTC)
        windows = list(_iter_windows(start, end, max_days=30))

        assert len(windows) == 3
        assert windows[0][0] == start
        assert windows[-1][1] == end
        # Contiguous, each no wider than 30 days, strictly ascending.
        for i, (ws, we) in enumerate(windows):
            assert ws < we
            assert (we - ws).days <= 30
            if i > 0:
                assert ws == windows[i - 1][1]


class TestToDatetime:
    @parameterized.expand(
        [
            ("none", None, None),
            ("naive_string", "2024-01-01T00:00:00", datetime(2024, 1, 1, tzinfo=UTC)),
            ("z_string", "2024-01-01T00:00:00Z", datetime(2024, 1, 1, tzinfo=UTC)),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: Optional[datetime]) -> None:
        assert _to_datetime(value) == expected

    def test_naive_datetime_gets_utc(self) -> None:
        assert _to_datetime(datetime(2024, 1, 1)) == datetime(2024, 1, 1, tzinfo=UTC)


class TestWindowsForAccount:
    def test_non_windowed_endpoint_is_single_none(self) -> None:
        windows = _windows_for_account(AWIN_ENDPOINTS["programmes"], False, None)
        assert windows == [None]

    @freeze_time("2024-06-01")
    def test_reports_use_lookback_window_regardless_of_incremental(self) -> None:
        windows = _windows_for_account(AWIN_ENDPOINTS["reports_advertiser"], True, datetime(2020, 1, 1, tzinfo=UTC))
        # 30-day rolling snapshot ending now, not the stale 2020 cursor.
        assert windows is not None and len(windows) == 1
        assert windows[0] is not None
        assert windows[0][0] == datetime(2024, 5, 2, tzinfo=UTC)
        assert windows[0][1] == datetime(2024, 6, 1, tzinfo=UTC)

    @freeze_time("2024-06-01")
    def test_transactions_incremental_windows_start_at_last_value(self) -> None:
        last_value = datetime(2024, 5, 15, tzinfo=UTC)
        windows = _windows_for_account(AWIN_ENDPOINTS["transactions"], True, last_value)
        assert windows[0] is not None
        assert windows[0][0] == last_value

    @freeze_time("2024-06-01")
    def test_transactions_full_refresh_backfills(self) -> None:
        windows = _windows_for_account(AWIN_ENDPOINTS["transactions"], False, None)
        # 365-day backfill chunked into 30-day windows.
        assert windows[0] is not None
        assert windows[0][0] == datetime(2023, 6, 2, tzinfo=UTC)
        assert len(windows) >= 12

    @freeze_time("2024-06-01")
    def test_future_cursor_yields_no_windows(self) -> None:
        windows = _windows_for_account(AWIN_ENDPOINTS["transactions"], True, datetime(2025, 1, 1, tzinfo=UTC))
        assert windows == []


class TestBuildWindowParams:
    def test_transactions_datetime_format_and_date_type(self) -> None:
        params = _build_window_params(
            AWIN_ENDPOINTS["transactions"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC),
            incremental_field="transactionDate",
        )
        assert params["startDate"] == "2024-01-01T00:00:00"
        assert params["endDate"] == "2024-01-31T00:00:00"
        assert params["timezone"] == "UTC"
        assert params["dateType"] == "transaction"

    def test_transactions_validation_date_maps_to_validation_date_type(self) -> None:
        params = _build_window_params(
            AWIN_ENDPOINTS["transactions"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC),
            incremental_field="validationDate",
        )
        assert params["dateType"] == "validation"

    def test_reports_use_date_only_format_and_no_date_type(self) -> None:
        params = _build_window_params(
            AWIN_ENDPOINTS["reports_advertiser"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC),
            incremental_field=None,
        )
        assert params["startDate"] == "2024-01-01"
        assert params["endDate"] == "2024-01-31"
        assert "dateType" not in params


class TestRowsFromResponse:
    def test_accounts_reads_wrapped_key(self) -> None:
        data = {"accounts": [{"accountId": 1}, {"accountId": 2}]}
        rows = _rows_from_response(AWIN_ENDPOINTS["accounts"], data, publisher_id=None)
        assert rows == [{"accountId": 1}, {"accountId": 2}]

    def test_bare_list_endpoint(self) -> None:
        data = [{"id": 1}, {"id": 2}]
        rows = _rows_from_response(AWIN_ENDPOINTS["transactions"], data, publisher_id=99)
        assert rows == [{"id": 1}, {"id": 2}]

    def test_inject_publisher_id_when_configured(self) -> None:
        data = [{"id": 1}]
        rows = _rows_from_response(AWIN_ENDPOINTS["programmes"], data, publisher_id=42)
        assert rows == [{"id": 1, "publisherId": 42}]

    def test_inject_does_not_overwrite_existing_publisher_id(self) -> None:
        data = [{"id": 1, "publisherId": 7}]
        rows = _rows_from_response(AWIN_ENDPOINTS["programmes"], data, publisher_id=42)
        assert rows == [{"id": 1, "publisherId": 7}]

    def test_non_dict_rows_are_dropped(self) -> None:
        data = [{"id": 1}, "junk", None]
        rows = _rows_from_response(AWIN_ENDPOINTS["transactions"], data, publisher_id=1)
        assert rows == [{"id": 1}]


class TestDiscoverPublisherIds:
    def test_filters_publisher_accounts_and_sorts_and_dedupes(self) -> None:
        with patch.object(awin, "_fetch") as mock_fetch:
            mock_fetch.return_value = {
                "accounts": [
                    {"accountId": 3, "accountType": "publisher"},
                    {"accountId": 1, "accountType": "publisher"},
                    {"accountId": 2, "accountType": "advertiser"},
                    {"accountId": 1, "accountType": "publisher"},
                ]
            }
            ids = _discover_publisher_ids(MagicMock(), {}, MagicMock())
        assert ids == [1, 3]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with patch.object(awin, "make_tracked_session") as mock_session:
            response = MagicMock()
            response.status_code = status
            mock_session.return_value.get.return_value = response
            assert validate_credentials("token") is expected

    def test_exception_is_false(self) -> None:
        with patch.object(awin, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("token") is False


class TestGetRows:
    def test_accounts_endpoint_yields_accounts_without_fanout(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(awin, "make_tracked_session"),
            patch.object(awin, "_fetch", return_value={"accounts": [{"accountId": 1}]}) as mock_fetch,
        ):
            batches = list(get_rows("token", "accounts", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"accountId": 1}]]
        # A single call to /accounts, no per-publisher fan-out.
        assert mock_fetch.call_count == 1

    @freeze_time("2024-06-01")
    def test_fanout_yields_per_account_and_saves_state(self) -> None:
        manager = FakeResumableManager()

        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {
                    "accounts": [
                        {"accountId": 10, "accountType": "publisher"},
                        {"accountId": 20, "accountType": "publisher"},
                    ]
                }
            return [{"id": 1, "publisherId": 999}]

        with patch.object(awin, "make_tracked_session"), patch.object(awin, "_fetch", side_effect=fake_fetch):
            batches = list(get_rows("token", "programmes", MagicMock(), manager))  # type: ignore[arg-type]

        # One batch per publisher account, publisherId injected only when absent.
        assert len(batches) == 2
        assert {row["publisherId"] for batch in batches for row in batch} == {999}
        # State saved after each account so a crash resumes at the right one.
        assert [s.account_id for s in manager.saved] == [10, 20]

    @freeze_time("2024-06-01")
    def test_resume_skips_already_synced_accounts(self) -> None:
        manager = FakeResumableManager(state=AwinResumeConfig(account_id=20, window_start=None))
        fetched_publishers: list[int] = []

        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {
                    "accounts": [
                        {"accountId": 10, "accountType": "publisher"},
                        {"accountId": 20, "accountType": "publisher"},
                        {"accountId": 30, "accountType": "publisher"},
                    ]
                }
            fetched_publishers.append(int(path.split("/")[2]))
            return [{"id": 1}]

        with patch.object(awin, "make_tracked_session"), patch.object(awin, "_fetch", side_effect=fake_fetch):
            list(get_rows("token", "programmes", MagicMock(), manager))  # type: ignore[arg-type]

        # Account 10 already synced before the crash; resume starts at 20.
        assert fetched_publishers == [20, 30]

    @freeze_time("2024-06-01")
    def test_windowed_fanout_arrives_in_globally_ascending_order(self) -> None:
        # Two accounts, multiple 30-day windows each. To keep the asc watermark monotonic, every
        # account's window N must be fetched before any account's window N+1 (windows OUTER, accounts
        # INNER) — not one account fully before the next.
        manager = FakeResumableManager()
        seen_starts: list[str] = []

        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {
                    "accounts": [
                        {"accountId": 10, "accountType": "publisher"},
                        {"accountId": 20, "accountType": "publisher"},
                    ]
                }
            seen_starts.append(params["startDate"])
            return [{"id": 1}]

        with patch.object(awin, "make_tracked_session"), patch.object(awin, "_fetch", side_effect=fake_fetch):
            list(get_rows("token", "transactions", MagicMock(), manager, should_use_incremental_field=False))  # type: ignore[arg-type]

        # startDate is non-decreasing across the whole run despite fanning out over two accounts.
        assert seen_starts == sorted(seen_starts)
        # Each window's startDate appears once per account (two accounts).
        assert all(count == 2 for count in _counts(seen_starts).values())

    @freeze_time("2024-06-01")
    def test_no_publisher_accounts_yields_nothing(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(awin, "make_tracked_session"),
            patch.object(awin, "_fetch", return_value={"accounts": []}),
        ):
            batches = list(get_rows("token", "programmes", MagicMock(), manager))  # type: ignore[arg-type]
        assert batches == []


class TestAwinSource:
    @parameterized.expand(
        [
            ("accounts", ["accountId"], None),
            ("programmes", ["publisherId", "id"], None),
            ("transactions", ["id"], "transactionDate"),
            ("reports_advertiser", ["publisherId", "advertiserId"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], partition_key: Optional[str]) -> None:
        response = awin_source("token", endpoint, MagicMock(), FakeResumableManager())  # type: ignore[arg-type]
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
