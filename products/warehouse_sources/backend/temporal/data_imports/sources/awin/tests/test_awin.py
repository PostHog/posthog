from datetime import UTC, datetime
from typing import Any, Optional

import time_machine
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.awin import awin
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.awin import (
    AwinFanoutTarget,
    AwinResumeConfig,
    _build_window_params,
    _discover_account_ids,
    _discover_joined_advertiser_ids,
    _fanout_targets,
    _format_path,
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

    @parameterized.expand([("reports_advertiser",), ("reports_publisher",)])
    @time_machine.travel("2024-06-01", tick=False)
    def test_reports_use_lookback_window_regardless_of_incremental(self, endpoint: str) -> None:
        windows = _windows_for_account(AWIN_ENDPOINTS[endpoint], True, datetime(2020, 1, 1, tzinfo=UTC))
        # 30-day rolling snapshot ending now, not the stale 2020 cursor.
        assert windows is not None and len(windows) == 1
        assert windows[0] is not None
        assert windows[0][0] == datetime(2024, 5, 2, tzinfo=UTC)
        assert windows[0][1] == datetime(2024, 6, 1, tzinfo=UTC)

    @time_machine.travel("2024-06-01", tick=False)
    def test_transactions_incremental_windows_start_at_last_value(self) -> None:
        last_value = datetime(2024, 5, 15, tzinfo=UTC)
        windows = _windows_for_account(AWIN_ENDPOINTS["transactions"], True, last_value)
        assert windows[0] is not None
        assert windows[0][0] == last_value

    @time_machine.travel("2024-06-01", tick=False)
    def test_transactions_full_refresh_backfills(self) -> None:
        windows = _windows_for_account(AWIN_ENDPOINTS["transactions"], False, None)
        # 365-day backfill chunked into 30-day windows.
        assert windows[0] is not None
        assert windows[0][0] == datetime(2023, 6, 2, tzinfo=UTC)
        assert len(windows) >= 12

    @time_machine.travel("2024-06-01", tick=False)
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
            region="GB",
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
            region="GB",
        )
        assert params["dateType"] == "validation"

    def test_reports_use_date_only_format_and_no_date_type(self) -> None:
        params = _build_window_params(
            AWIN_ENDPOINTS["reports_advertiser"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC),
            incremental_field=None,
            region="GB",
        )
        assert params["startDate"] == "2024-01-01"
        assert params["endDate"] == "2024-01-31"
        assert "dateType" not in params

    def test_reports_advertiser_includes_region(self) -> None:
        # Awin's aggregated advertiser report 400s without `region` because it's a required param
        # the API has no "all regions" value for.
        params = _build_window_params(
            AWIN_ENDPOINTS["reports_advertiser"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC),
            incremental_field=None,
            region="US",
        )
        assert params["region"] == "US"

    def test_reports_publisher_does_not_include_region(self) -> None:
        # Unlike its publisher-side counterpart, Awin's advertiser-side report takes no region param.
        params = _build_window_params(
            AWIN_ENDPOINTS["reports_publisher"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC),
            incremental_field=None,
            region="US",
        )
        assert params == {"startDate": "2024-01-01", "endDate": "2024-01-31", "timezone": "UTC"}

    def test_transactions_does_not_include_region(self) -> None:
        # Only endpoints marked `requires_region` (the aggregated reports) send the param.
        params = _build_window_params(
            AWIN_ENDPOINTS["transactions"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC),
            incremental_field="transactionDate",
            region="US",
        )
        assert "region" not in params


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

    def test_commission_groups_flattens_envelope_onto_each_group(self) -> None:
        # Awin hangs the rate validity window off the envelope, not off each group, so without the
        # copy every commission_groups row loses when its rate applied.
        data = {
            "advertiser": 9,
            "publisher": 42,
            "ratesStart": "2024-01-01T00:00:00Z",
            "ratesEnd": "2024-06-01T00:00:00Z",
            "commissionGroups": [{"groupId": 1, "type": "fix"}, {"groupId": 2, "type": "percentage"}],
        }
        rows = _rows_from_response(AWIN_ENDPOINTS["commission_groups"], data, publisher_id=42, advertiser_id=9)

        assert rows == [
            {
                "groupId": 1,
                "type": "fix",
                "ratesStart": "2024-01-01T00:00:00Z",
                "ratesEnd": "2024-06-01T00:00:00Z",
                "publisherId": 42,
                "advertiserId": 9,
            },
            {
                "groupId": 2,
                "type": "percentage",
                "ratesStart": "2024-01-01T00:00:00Z",
                "ratesEnd": "2024-06-01T00:00:00Z",
                "publisherId": 42,
                "advertiserId": 9,
            },
        ]

    def test_commission_groups_tolerates_a_missing_rates_end(self) -> None:
        # ratesEnd is omitted while the rates are ongoing.
        data = {"ratesStart": "2024-01-01T00:00:00Z", "commissionGroups": [{"groupId": 1}]}
        rows = _rows_from_response(AWIN_ENDPOINTS["commission_groups"], data, publisher_id=42, advertiser_id=9)
        assert rows == [{"groupId": 1, "ratesStart": "2024-01-01T00:00:00Z", "publisherId": 42, "advertiserId": 9}]

    def test_programme_details_object_becomes_one_row_with_both_ids(self) -> None:
        # The payload is the programme, not a list of them, and carries neither id in its root.
        data = {"kpi": {"epc": 0.5}, "programmeInfo": {"id": 9, "name": "Acme"}}
        rows = _rows_from_response(AWIN_ENDPOINTS["programme_details"], data, publisher_id=42, advertiser_id=9)
        assert rows == [
            {"kpi": {"epc": 0.5}, "programmeInfo": {"id": 9, "name": "Acme"}, "publisherId": 42, "advertiserId": 9}
        ]

    def test_advertiser_publishers_gets_the_advertiser_id_injected(self) -> None:
        # The rows carry only the publisher's own fields, so without this the lookup can't be joined
        # back to the advertiser it belongs to.
        data = [{"id": 7, "name": "Some publisher"}]
        rows = _rows_from_response(AWIN_ENDPOINTS["advertiser_publishers"], data, publisher_id=None, advertiser_id=90)
        assert rows == [{"id": 7, "name": "Some publisher", "advertiserId": 90}]


class TestDiscoverAccountIds:
    @parameterized.expand([("publisher", [1, 3]), ("advertiser", [2])])
    def test_filters_by_account_type_and_sorts_and_dedupes(self, account_type: str, expected: list[int]) -> None:
        with patch.object(awin, "_fetch") as mock_fetch:
            mock_fetch.return_value = {
                "accounts": [
                    {"accountId": 3, "accountType": "publisher"},
                    {"accountId": 1, "accountType": "publisher"},
                    {"accountId": 2, "accountType": "advertiser"},
                    {"accountId": 1, "accountType": "publisher"},
                ]
            }
            ids = _discover_account_ids(MagicMock(), {}, MagicMock(), account_type)
        assert ids == expected


class TestDiscoverJoinedAdvertiserIds:
    def test_reads_programme_ids_from_the_joined_programmes_list(self) -> None:
        with patch.object(awin, "_fetch") as mock_fetch:
            mock_fetch.return_value = [{"id": 7}, {"id": 3}, {"id": 7}, "junk", {"name": "no id"}]
            ids = _discover_joined_advertiser_ids(MagicMock(), {}, MagicMock(), publisher_id=10)

        assert ids == [3, 7]
        # Bounded to joined programmes; the network-wide default would be enormous.
        assert mock_fetch.call_args.args[1] == "/publishers/10/programmes"
        assert mock_fetch.call_args.args[3] == {"relationship": "joined"}


class TestFanoutTargets:
    def _fetch_for(self, programmes_by_publisher: dict[int, list[int]]):
        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {
                    "accounts": [
                        {"accountId": 10, "accountType": "publisher"},
                        {"accountId": 20, "accountType": "publisher"},
                        {"accountId": 90, "accountType": "advertiser"},
                    ]
                }
            publisher_id = int(path.split("/")[2])
            return [{"id": advertiser_id} for advertiser_id in programmes_by_publisher[publisher_id]]

        return fake_fetch

    def test_advertiser_fanout_uses_advertiser_accounts_only(self) -> None:
        with patch.object(awin, "_fetch", side_effect=self._fetch_for({})):
            targets = _fanout_targets(AWIN_ENDPOINTS["reports_publisher"], MagicMock(), {}, MagicMock())
        assert targets == [AwinFanoutTarget(account_id=90)]

    def test_publisher_fanout_uses_publisher_accounts_only(self) -> None:
        with patch.object(awin, "_fetch", side_effect=self._fetch_for({})):
            targets = _fanout_targets(AWIN_ENDPOINTS["transactions"], MagicMock(), {}, MagicMock())
        assert targets == [AwinFanoutTarget(account_id=10), AwinFanoutTarget(account_id=20)]

    def test_programme_fanout_pairs_each_publisher_with_its_joined_advertisers(self) -> None:
        with patch.object(awin, "_fetch", side_effect=self._fetch_for({10: [1, 2], 20: [2]})):
            targets = _fanout_targets(AWIN_ENDPOINTS["commission_groups"], MagicMock(), {}, MagicMock())

        assert targets == [
            AwinFanoutTarget(account_id=10, advertiser_id=1),
            AwinFanoutTarget(account_id=10, advertiser_id=2),
            AwinFanoutTarget(account_id=20, advertiser_id=2),
        ]


class TestFormatPath:
    @parameterized.expand(
        [
            ("transactions", "/publishers/5/transactions/"),
            ("commission_groups", "/publishers/5/commissiongroups"),
            ("reports_publisher", "/advertisers/5/reports/publisher"),
            ("advertiser_publishers", "/advertisers/5/publishers"),
        ]
    )
    def test_account_id_lands_in_the_right_path_segment(self, endpoint: str, expected: str) -> None:
        # Advertiser-scoped endpoints take the account id in /advertisers/, publisher-scoped ones in
        # /publishers/ — swapping them 404s (or worse, reads another account's data).
        target = AwinFanoutTarget(account_id=5, advertiser_id=9)
        assert _format_path(AWIN_ENDPOINTS[endpoint], target) == expected


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
            batches = list(get_rows("token", "accounts", MagicMock(), manager, region="GB"))  # type: ignore[arg-type]

        assert batches == [[{"accountId": 1}]]
        # A single call to /accounts, no per-publisher fan-out.
        assert mock_fetch.call_count == 1

    @time_machine.travel("2024-06-01", tick=False)
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
            batches = list(get_rows("token", "programmes", MagicMock(), manager, region="GB"))  # type: ignore[arg-type]

        # One batch per publisher account, publisherId injected only when absent.
        assert len(batches) == 2
        assert {row["publisherId"] for batch in batches for row in batch} == {999}
        # State saved after each account so a crash resumes at the right one.
        assert [s.account_id for s in manager.saved] == [10, 20]

    @time_machine.travel("2024-06-01", tick=False)
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
            list(get_rows("token", "programmes", MagicMock(), manager, region="GB"))  # type: ignore[arg-type]

        # Account 10 already synced before the crash; resume starts at 20.
        assert fetched_publishers == [20, 30]

    @time_machine.travel("2024-06-01", tick=False)
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
            list(
                get_rows(
                    "token",
                    "transactions",
                    MagicMock(),
                    manager,  # type: ignore[arg-type]
                    region="GB",
                    should_use_incremental_field=False,
                )
            )

        # startDate is non-decreasing across the whole run despite fanning out over two accounts.
        assert seen_starts == sorted(seen_starts)
        # Each window's startDate appears once per account (two accounts).
        assert all(count == 2 for count in _counts(seen_starts).values())

    @time_machine.travel("2024-06-01", tick=False)
    def test_no_publisher_accounts_yields_nothing(self) -> None:
        manager = FakeResumableManager()
        with (
            patch.object(awin, "make_tracked_session"),
            patch.object(awin, "_fetch", return_value={"accounts": []}),
        ):
            batches = list(get_rows("token", "programmes", MagicMock(), manager, region="GB"))  # type: ignore[arg-type]
        assert batches == []

    @time_machine.travel("2024-06-01", tick=False)
    def test_advertiser_fanout_skips_publisher_accounts(self) -> None:
        # /advertisers paths only accept advertiser accounts; fanning out over publisher ids 404s.
        manager = FakeResumableManager()
        seen_paths: list[str] = []

        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {
                    "accounts": [
                        {"accountId": 10, "accountType": "publisher"},
                        {"accountId": 90, "accountType": "advertiser"},
                    ]
                }
            seen_paths.append(path)
            return [{"id": 7}]

        with patch.object(awin, "make_tracked_session"), patch.object(awin, "_fetch", side_effect=fake_fetch):
            batches = list(get_rows("token", "advertiser_publishers", MagicMock(), manager, region="GB"))  # type: ignore[arg-type]

        assert seen_paths == ["/advertisers/90/publishers"]
        assert batches == [[{"id": 7, "advertiserId": 90}]]

    @time_machine.travel("2024-06-01", tick=False)
    def test_programme_fanout_sends_advertiser_id_per_joined_programme(self) -> None:
        manager = FakeResumableManager()
        requests_made: list[tuple[str, Any]] = []

        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {"accounts": [{"accountId": 10, "accountType": "publisher"}]}
            if path.endswith("/programmes"):
                return [{"id": 1}, {"id": 2}]
            requests_made.append((path, params))
            return {"commissionGroups": [{"groupId": 100}]}

        with patch.object(awin, "make_tracked_session"), patch.object(awin, "_fetch", side_effect=fake_fetch):
            batches = list(get_rows("token", "commission_groups", MagicMock(), manager, region="GB"))  # type: ignore[arg-type]

        # advertiserId is a required query param on this publisher-scoped path — without it Awin 400s.
        assert requests_made == [
            ("/publishers/10/commissiongroups", {"extraConditionsDetails": "true", "advertiserId": "1"}),
            ("/publishers/10/commissiongroups", {"extraConditionsDetails": "true", "advertiserId": "2"}),
        ]
        assert [row["advertiserId"] for batch in batches for row in batch] == [1, 2]
        # State carries the programme too, so a crash resumes at the right (publisher, advertiser) pair.
        assert [(s.account_id, s.advertiser_id) for s in manager.saved] == [(10, 1), (10, 2)]

    @time_machine.travel("2024-06-01", tick=False)
    def test_programme_fanout_resumes_at_the_saved_pair(self) -> None:
        manager = FakeResumableManager(state=AwinResumeConfig(account_id=10, advertiser_id=2, window_start=None))
        fetched_advertisers: list[str] = []

        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {"accounts": [{"accountId": 10, "accountType": "publisher"}]}
            if path.endswith("/programmes"):
                return [{"id": 1}, {"id": 2}, {"id": 3}]
            fetched_advertisers.append(params["advertiserId"])
            return {}

        with patch.object(awin, "make_tracked_session"), patch.object(awin, "_fetch", side_effect=fake_fetch):
            list(get_rows("token", "programme_details", MagicMock(), manager, region="GB"))  # type: ignore[arg-type]

        # Programme 1 was already done before the crash; the pair bookmark restarts at 2.
        assert fetched_advertisers == ["2", "3"]

    @time_machine.travel("2024-06-01", tick=False)
    def test_programme_fanout_static_params_are_not_mutated_between_requests(self) -> None:
        # The endpoint's static extra_params dict is shared by every request, so writing advertiserId
        # into it would leak the previous programme's id into later requests.
        manager = FakeResumableManager()
        seen_params: list[dict[str, Any]] = []

        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {"accounts": [{"accountId": 10, "accountType": "publisher"}]}
            if path.endswith("/programmes"):
                return [{"id": 1}, {"id": 2}]
            seen_params.append(dict(params))
            return {}

        with patch.object(awin, "make_tracked_session"), patch.object(awin, "_fetch", side_effect=fake_fetch):
            list(get_rows("token", "programme_details", MagicMock(), manager, region="GB"))  # type: ignore[arg-type]

        assert seen_params == [
            {"relationship": "joined", "advertiserId": "1"},
            {"relationship": "joined", "advertiserId": "2"},
        ]
        assert AWIN_ENDPOINTS["programme_details"].extra_params == {"relationship": "joined"}

    @time_machine.travel("2024-06-01", tick=False)
    def test_reports_advertiser_request_carries_region(self) -> None:
        manager = FakeResumableManager()
        seen_params: list[dict[str, Any]] = []

        def fake_fetch(session: Any, path: str, headers: Any, params: Any, logger: Any) -> Any:
            if path == "/accounts":
                return {"accounts": [{"accountId": 10, "accountType": "publisher"}]}
            seen_params.append(params)
            return []

        with patch.object(awin, "make_tracked_session"), patch.object(awin, "_fetch", side_effect=fake_fetch):
            list(get_rows("token", "reports_advertiser", MagicMock(), manager, region="DE"))  # type: ignore[arg-type]

        # Without this, Awin rejects the request with a 400 (region has no "all regions" value).
        assert seen_params == [{"startDate": "2024-05-02", "endDate": "2024-06-01", "timezone": "UTC", "region": "DE"}]


class TestAwinSource:
    @parameterized.expand(
        [
            ("accounts", ["accountId"], None),
            ("programmes", ["publisherId", "id"], None),
            ("transactions", ["id"], "transactionDate"),
            ("reports_advertiser", ["publisherId", "advertiserId"], None),
            ("reports_publisher", ["advertiserId", "publisherId"], None),
            ("advertiser_publishers", ["advertiserId", "id"], None),
            ("commission_groups", ["publisherId", "advertiserId", "groupId"], None),
            ("programme_details", ["publisherId", "advertiserId"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], partition_key: Optional[str]) -> None:
        response = awin_source("token", endpoint, MagicMock(), FakeResumableManager(), region="GB")  # type: ignore[arg-type]
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
