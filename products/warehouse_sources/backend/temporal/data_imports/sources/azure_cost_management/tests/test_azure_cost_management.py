from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.azure_cost_management import (
    LOGIN_HOST,
    MANAGEMENT_HOST,
    AzureCostManagementClient,
    AzureCostManagementResumeConfig,
    AzureCostManagementRetryableError,
    _parse_usage_date,
    _retry_after_seconds,
    _snake_case,
    _validated_next_link,
    azure_cost_management_source,
    build_query_body,
    build_windows,
    get_rows,
    normalize_scope,
    resolve_window_start,
    rows_from_dimensions,
    rows_from_query_result,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.settings import (
    AZURE_COST_MANAGEMENT_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow

TRANSPORT_MODULE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.azure_cost_management"
)


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        headers: Optional[dict[str, str]] = None,
        text: str = "",
        reason: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}
        self.text = text
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class _FakeSession:
    """Serves queued responses in order and records every call the client made."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _pop(self, method: str, url: str, kwargs: dict[str, Any]) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self._responses.pop(0)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._pop("POST", url, kwargs)

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._pop("GET", url, kwargs)


class _FakeResumeManager(ResumableSourceManager[AzureCostManagementResumeConfig]):
    def __init__(self, state: AzureCostManagementResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[AzureCostManagementResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> AzureCostManagementResumeConfig | None:
        return self.state

    def save_state(self, data: AzureCostManagementResumeConfig) -> None:
        self.saved.append(data)


def _token_response() -> _FakeResponse:
    return _FakeResponse(200, {"access_token": "access-token", "expires_in": 3599})


def _query_response(
    rows: list[list[Any]], columns: Optional[list[str]] = None, next_link: Optional[str] = None
) -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "properties": {
                "columns": [
                    {"name": name, "type": "String"} for name in (columns or ["Cost", "UsageDate", "ServiceName"])
                ],
                "rows": rows,
                "nextLink": next_link,
            }
        },
    )


def _client(session: _FakeSession, sleeps: Optional[list[float]] = None) -> AzureCostManagementClient:
    def _sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    with mock.patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
        return AzureCostManagementClient("tenant", "client", "secret", mock.MagicMock(), sleep=_sleep)


def _collect(rows: Iterable[Any]) -> list[list[dict[str, Any]]]:
    return list(cast("Iterable[Any]", rows))


class TestSnakeCase:
    @parameterized.expand(
        [
            ("ServiceName", "service_name"),
            ("ResourceGroupName", "resource_group_name"),
            ("ResourceId", "resource_id"),
            ("UsageDate", "usage_date"),
            ("Cost", "cost"),
            ("CostUSD", "cost_usd"),
            ("PreTaxCost", "pre_tax_cost"),
        ]
    )
    def test_column_names(self, azure_name: str, expected: str) -> None:
        assert _snake_case(azure_name) == expected


class TestNormalizeScope:
    @parameterized.expand(
        [
            ("/subscriptions/abc/", "subscriptions/abc"),
            ("  subscriptions/abc  ", "subscriptions/abc"),
            (
                "providers/Microsoft.Billing/billingAccounts/123",
                "providers/Microsoft.Billing/billingAccounts/123",
            ),
        ]
    )
    def test_trims_to_arm_path(self, raw: str, expected: str) -> None:
        assert normalize_scope(raw) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("only_slashes", "///"),
            # A scope carrying its own host would repoint our credentialed requests at it.
            ("absolute_url", "https://evil.example/subscriptions/abc"),
            ("protocol_relative", "//evil.example/subscriptions/abc"),
            # A `?`/`#` would push the appended Cost Management path into the query/fragment,
            # leaving the credentialed request pointed at an arbitrary ARM operation.
            ("query_delimiter", "subscriptions/abc/resources?api-version=2021-04-01"),
            ("fragment_delimiter", "subscriptions/abc/resources#"),
            ("backslash", "subscriptions\\abc"),
        ]
    )
    def test_rejects_non_path_scopes(self, _name: str, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_scope(raw)


class TestValidatedNextLink:
    def test_accepts_arm_link(self) -> None:
        link = f"{MANAGEMENT_HOST}/subscriptions/abc/providers/Microsoft.CostManagement/query?$skiptoken=x"
        assert _validated_next_link(link) == link

    @parameterized.expand(
        [
            ("other_host", "https://evil.example/next"),
            ("lookalike_host", "https://management.azure.com.evil.example/next"),
            ("http_scheme", "http://management.azure.com/next"),
        ]
    )
    def test_rejects_off_host_link(self, _name: str, link: str) -> None:
        with pytest.raises(ValueError):
            _validated_next_link(link)


class TestParseUsageDate:
    @parameterized.expand(
        [
            ("int_yyyymmdd", 20240115, "2024-01-15"),
            ("str_yyyymmdd", "20240115", "2024-01-15"),
            ("iso_datetime", "2024-01-15T00:00:00", "2024-01-15"),
            ("iso_datetime_zulu", "2024-01-15T00:00:00Z", "2024-01-15"),
            ("iso_date", "2024-01-15", "2024-01-15"),
            ("none", None, None),
            ("unparseable", "not-a-date", "not-a-date"),
        ]
    )
    def test_normalizes_to_iso_day(self, _name: str, raw: Any, expected: Any) -> None:
        assert _parse_usage_date(raw) == expected


class TestRowsFromQueryResult:
    def test_zips_columns_and_rows_and_stamps_scope(self) -> None:
        payload = {
            "properties": {
                "columns": [{"name": "Cost"}, {"name": "UsageDate"}, {"name": "ServiceName"}, {"name": "Currency"}],
                "rows": [[1.5, 20240115, "Storage", "USD"], [2.5, 20240116, "Virtual Machines", "USD"]],
                "nextLink": None,
            }
        }

        rows, next_link = rows_from_query_result(payload, "subscriptions/abc")

        assert next_link is None
        assert rows == [
            {
                "cost": 1.5,
                "usage_date": "2024-01-15",
                "service_name": "Storage",
                "currency": "USD",
                "scope": "subscriptions/abc",
            },
            {
                "cost": 2.5,
                "usage_date": "2024-01-16",
                "service_name": "Virtual Machines",
                "currency": "USD",
                "scope": "subscriptions/abc",
            },
        ]

    def test_returns_next_link_when_present(self) -> None:
        payload = {"properties": {"columns": [], "rows": [], "nextLink": f"{MANAGEMENT_HOST}/next"}}
        assert rows_from_query_result(payload, "s")[1] == f"{MANAGEMENT_HOST}/next"

    @parameterized.expand([("not_a_dict", []), ("missing_properties", {}), ("null_properties", {"properties": None})])
    def test_tolerates_unexpected_payloads(self, _name: str, payload: Any) -> None:
        assert rows_from_query_result(payload, "s") == ([], None)


class TestRowsFromDimensions:
    def test_flattens_properties(self) -> None:
        payload = {
            "value": [
                {
                    "id": "/subscriptions/abc/providers/Microsoft.CostManagement/dimensions/ResourceGroupName",
                    "name": "ResourceGroupName",
                    "type": "Microsoft.CostManagement/dimensions",
                    "properties": {
                        "category": "ResourceGroupName",
                        "description": "Resource group",
                        "filterEnabled": True,
                        "groupingEnabled": True,
                        "total": 2,
                        "data": ["rg-a", "rg-b"],
                    },
                }
            ]
        }

        rows = rows_from_dimensions(payload, "subscriptions/abc")

        assert len(rows) == 1
        assert rows[0]["scope"] == "subscriptions/abc"
        assert rows[0]["name"] == "ResourceGroupName"
        assert rows[0]["grouping_enabled"] is True
        assert rows[0]["data"] == ["rg-a", "rg-b"]

    def test_tolerates_missing_properties(self) -> None:
        assert rows_from_dimensions({"value": [{"name": "X"}]}, "s")[0]["category"] is None


class TestBuildWindows:
    def test_single_window_for_short_range(self) -> None:
        assert build_windows(date(2024, 1, 1), date(2024, 1, 10)) == [
            SyncWindow(start=date(2024, 1, 1), end=date(2024, 1, 10))
        ]

    def test_splits_at_the_api_max_range(self) -> None:
        windows = build_windows(date(2023, 1, 1), date(2024, 6, 30))

        assert windows == [
            SyncWindow(start=date(2023, 1, 1), end=date(2023, 12, 31)),
            SyncWindow(start=date(2024, 1, 1), end=date(2024, 6, 30)),
        ]

    def test_windows_are_contiguous_and_cover_the_range(self) -> None:
        windows = build_windows(date(2020, 1, 1), date(2024, 1, 1))

        assert windows[0].start == date(2020, 1, 1)
        assert windows[-1].end == date(2024, 1, 1)
        for earlier, later in zip(windows, windows[1:]):
            assert later.start == earlier.end + timedelta(days=1)

    def test_empty_when_start_after_end(self) -> None:
        assert build_windows(date(2024, 2, 1), date(2024, 1, 1)) == []


class TestResolveWindowStart:
    TODAY = date(2024, 6, 1)

    def test_incremental_watermark_wins(self) -> None:
        assert resolve_window_start(True, "2024-05-20", "2020-01-01", self.TODAY) == date(
            2024, 5, 20
        )  # the watermark day is re-pulled, since Azure restates it

    def test_future_watermark_is_clamped_to_today(self) -> None:
        assert resolve_window_start(True, "2030-01-01", None, self.TODAY) == self.TODAY

    def test_falls_back_to_configured_start_date(self) -> None:
        assert resolve_window_start(False, "2024-05-20", "2023-03-04", self.TODAY) == date(2023, 3, 4)

    def test_falls_back_to_default_history_window(self) -> None:
        assert resolve_window_start(False, None, None, self.TODAY) == self.TODAY - timedelta(days=365)

    def test_unparseable_watermark_falls_through(self) -> None:
        assert resolve_window_start(True, "garbage", "2023-03-04", self.TODAY) == date(2023, 3, 4)


class TestBuildQueryBody:
    def test_cost_query_windows_and_sorts_ascending(self) -> None:
        body = build_query_body(AZURE_COST_MANAGEMENT_ENDPOINTS["cost_by_service"], date(2024, 1, 1), date(2024, 1, 31))

        assert body["type"] == "ActualCost"
        assert body["timeframe"] == "Custom"
        assert body["timePeriod"]["from"].startswith("2024-01-01")
        assert body["timePeriod"]["to"].startswith("2024-01-31")
        assert body["dataset"]["granularity"] == "Daily"
        assert body["dataset"]["grouping"] == [{"type": "Dimension", "name": "ServiceName"}]
        assert body["dataset"]["sorting"] == [{"direction": "Ascending", "name": "UsageDate"}]

    def test_amortized_query_uses_amortized_export_type(self) -> None:
        body = build_query_body(
            AZURE_COST_MANAGEMENT_ENDPOINTS["amortized_cost_by_service"], date(2024, 1, 1), date(2024, 1, 31)
        )
        assert body["type"] == "AmortizedCost"

    def test_forecast_excludes_actuals_and_does_not_sort(self) -> None:
        body = build_query_body(AZURE_COST_MANAGEMENT_ENDPOINTS["forecast"], date(2024, 1, 1), date(2024, 1, 31))

        assert body["includeActualCost"] is False
        assert body["includeFreshPartialCost"] is False
        assert "sorting" not in body["dataset"]


class TestRetryAfterSeconds:
    @parameterized.expand(
        [
            ("standard", {"Retry-After": "30"}, 30.0),
            ("consumption", {"x-ms-ratelimit-microsoft.consumption-retry-after": "45"}, 45.0),
            ("client_type", {"x-ms-ratelimit-microsoft.costmanagement-clienttype-retry-after": "12"}, 12.0),
            ("entity", {"x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "7"}, 7.0),
            ("capped", {"Retry-After": "100000"}, 120.0),
            ("non_numeric", {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}, None),
            ("absent", {}, None),
        ]
    )
    def test_reads_vendor_and_standard_headers(
        self, _name: str, headers: dict[str, str], expected: Optional[float]
    ) -> None:
        assert _retry_after_seconds(cast(Any, _FakeResponse(429, headers=headers))) == expected


class TestClientMintToken:
    def test_returns_access_token(self) -> None:
        session = _FakeSession([_token_response()])
        assert _client(session).mint_token() == "access-token"
        assert session.calls[0][1].startswith(f"{LOGIN_HOST}/tenant/oauth2/v2.0/token")
        assert session.calls[0][2]["data"]["grant_type"] == "client_credentials"

    @parameterized.expand([(400,), (401,)])
    def test_credential_failure_raises_with_login_host(self, status: int) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    status,
                    {"error": "invalid_client", "error_description": "Bad secret"},
                    reason="Bad Request" if status == 400 else "Unauthorized",
                )
            ]
        )
        with pytest.raises(requests.HTTPError) as error:
            _client(session).mint_token()

        # The message shape is what `get_non_retryable_errors` matches on.
        assert LOGIN_HOST in str(error.value)
        assert "Bad secret" in str(error.value)

    def test_missing_access_token_raises(self) -> None:
        session = _FakeSession([_FakeResponse(200, {"token_type": "Bearer"})])
        with pytest.raises(requests.HTTPError):
            _client(session).mint_token()


class TestClientRequest:
    def test_mints_a_token_and_sends_it_as_a_bearer(self) -> None:
        session = _FakeSession([_token_response(), _query_response([])])
        _client(session).request("POST", f"{MANAGEMENT_HOST}/q", {"a": 1})

        _method, _url, kwargs = session.calls[1]
        assert kwargs["headers"]["Authorization"] == "Bearer access-token"
        assert kwargs["headers"]["X-Ms-Command-Name"] == "PostHogDataWarehouse"
        assert kwargs["json"] == {"a": 1}

    def test_remints_once_on_401_then_succeeds(self) -> None:
        session = _FakeSession(
            [
                _token_response(),
                _FakeResponse(401, reason="Unauthorized"),
                _FakeResponse(200, {"access_token": "fresh-token"}),
                _query_response([[1, 20240101, "Storage"]]),
            ]
        )

        result = _client(session).request("POST", f"{MANAGEMENT_HOST}/q")

        assert result["properties"]["rows"] == [[1, 20240101, "Storage"]]
        assert session.calls[-1][2]["headers"]["Authorization"] == "Bearer fresh-token"

    def test_repeated_401_stops_after_one_remint(self) -> None:
        session = _FakeSession(
            [
                _token_response(),
                _FakeResponse(401, reason="Unauthorized"),
                _FakeResponse(200, {"access_token": "fresh-token"}),
                _FakeResponse(401, reason="Unauthorized"),
            ]
        )

        with pytest.raises(requests.HTTPError) as error:
            _client(session).request("POST", f"{MANAGEMENT_HOST}/q")

        assert "401 Client Error" in str(error.value)
        assert MANAGEMENT_HOST in str(error.value)

    @parameterized.expand([(429,), (500,), (503,)])
    def test_retries_transient_statuses_then_succeeds(self, status: int) -> None:
        sleeps: list[float] = []
        session = _FakeSession(
            [
                _token_response(),
                _FakeResponse(status, headers={"x-ms-ratelimit-microsoft.consumption-retry-after": "9"}),
                _query_response([]),
            ]
        )

        _client(session, sleeps).request("POST", f"{MANAGEMENT_HOST}/q")

        assert sleeps == [9.0]

    def test_exhausted_retries_raise_retryable_error(self) -> None:
        sleeps: list[float] = []
        session = _FakeSession([_token_response(), *[_FakeResponse(429) for _ in range(6)]])

        with pytest.raises(AzureCostManagementRetryableError):
            _client(session, sleeps).request("POST", f"{MANAGEMENT_HOST}/q")

        # Bounded: five sleeps then a raise, rather than an unbounded throttle loop.
        assert len(sleeps) == 5

    @parameterized.expand([(400,), (403,), (404,)])
    def test_permanent_client_errors_raise_http_error(self, status: int) -> None:
        session = _FakeSession(
            [
                _token_response(),
                _FakeResponse(status, {"error": {"code": "Denied", "message": "No access"}}, reason="Forbidden"),
            ]
        )

        with pytest.raises(requests.HTTPError) as error:
            _client(session).request("POST", f"{MANAGEMENT_HOST}/q")

        assert "No access" in str(error.value)


class TestValidateCredentials:
    def test_valid_when_token_and_scope_probe_succeed(self) -> None:
        session = _FakeSession([_token_response(), _FakeResponse(200, {"value": []})])
        with mock.patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("tenant", "client", "secret", "subscriptions/abc", "2025-03-01") == (True, None)

    def test_bad_scope_path_is_rejected_without_a_request(self) -> None:
        valid, message = validate_credentials("tenant", "client", "secret", "https://evil.example", "2025-03-01")

        assert valid is False
        assert message is not None

    def test_auth_failure_reports_credentials(self) -> None:
        session = _FakeSession([_FakeResponse(401, reason="Unauthorized")])
        with mock.patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("tenant", "client", "secret", "subscriptions/abc", "2025-03-01")

        assert valid is False
        assert message is not None and "Azure AD" in message

    def test_scope_failure_reports_role(self) -> None:
        session = _FakeSession([_token_response(), _FakeResponse(403, reason="Forbidden")])
        with mock.patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("tenant", "client", "secret", "subscriptions/abc", "2025-03-01")

        assert valid is False
        assert message is not None and "Cost Management Reader" in message


def _run_rows(
    session: _FakeSession,
    endpoint: str,
    manager: _FakeResumeManager,
    start_date: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    api_version: str = "2025-03-01",
) -> list[list[dict[str, Any]]]:
    with mock.patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
        return _collect(
            get_rows(
                tenant_id="tenant",
                client_id="client",
                client_secret="secret",
                scope="/subscriptions/abc/",
                endpoint=endpoint,
                start_date=start_date,
                api_version=api_version,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )


class TestGetRows:
    def setup_method(self) -> None:
        self.today = datetime.now(tz=UTC).date()

    def test_paginates_until_next_link_is_absent(self) -> None:
        next_link = f"{MANAGEMENT_HOST}/subscriptions/abc/providers/Microsoft.CostManagement/query?$skiptoken=abc"
        session = _FakeSession(
            [
                _token_response(),
                _query_response([[1.0, 20240101, "Storage"]], next_link=next_link),
                _query_response([[2.0, 20240102, "Storage"]]),
            ]
        )
        manager = _FakeResumeManager()

        batches = _run_rows(
            session, "cost_by_service", manager, start_date=(self.today - timedelta(days=2)).isoformat()
        )

        assert [len(batch) for batch in batches] == [1, 1]
        assert batches[0][0]["usage_date"] == "2024-01-01"
        # The second page is fetched from the returned link, not the base query URL.
        assert session.calls[2][1] == next_link
        # Checkpoint written after the first page is yielded, pointing at the page still to fetch.
        assert manager.saved == [
            AzureCostManagementResumeConfig(
                window_start=(self.today - timedelta(days=2)).isoformat(), next_link=next_link
            )
        ]

    def test_off_host_next_link_aborts_the_sync(self) -> None:
        session = _FakeSession(
            [
                _token_response(),
                _query_response([[1.0, 20240101, "Storage"]], next_link="https://evil.example/next"),
            ]
        )

        with pytest.raises(ValueError):
            _run_rows(
                session,
                "cost_by_service",
                _FakeResumeManager(),
                start_date=(self.today - timedelta(days=2)).isoformat(),
            )

    def test_checkpoints_between_windows(self) -> None:
        start = self.today - timedelta(days=400)
        session = _FakeSession([_token_response(), _query_response([[1.0, 20240101, "Storage"]]), _query_response([])])
        manager = _FakeResumeManager()

        _run_rows(session, "cost_by_service", manager, start_date=start.isoformat())

        expected_second_window_start = start + timedelta(days=365)
        assert manager.saved == [
            AzureCostManagementResumeConfig(window_start=expected_second_window_start.isoformat(), next_link=None)
        ]
        assert len(session.calls) == 3

    def test_resume_skips_windows_already_walked(self) -> None:
        start = self.today - timedelta(days=400)
        second_window_start = start + timedelta(days=365)
        session = _FakeSession([_token_response(), _query_response([[1.0, 20240101, "Storage"]])])
        manager = _FakeResumeManager(AzureCostManagementResumeConfig(window_start=second_window_start.isoformat()))

        _run_rows(session, "cost_by_service", manager, start_date=start.isoformat())

        # Only the un-walked window is requested.
        assert len(session.calls) == 2
        assert session.calls[1][2]["json"]["timePeriod"]["from"].startswith(second_window_start.isoformat())

    def test_resume_continues_from_the_saved_next_link(self) -> None:
        next_link = f"{MANAGEMENT_HOST}/subscriptions/abc/providers/Microsoft.CostManagement/query?$skiptoken=xyz"
        session = _FakeSession([_token_response(), _query_response([[1.0, 20240101, "Storage"]])])
        start = self.today - timedelta(days=2)
        manager = _FakeResumeManager(
            AzureCostManagementResumeConfig(window_start=start.isoformat(), next_link=next_link)
        )

        _run_rows(session, "cost_by_service", manager, start_date=start.isoformat())

        assert session.calls[1][1] == next_link

    def test_incremental_run_windows_from_the_watermark(self) -> None:
        watermark = self.today - timedelta(days=3)
        session = _FakeSession([_token_response(), _query_response([])])

        _run_rows(
            session,
            "cost_by_service",
            _FakeResumeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark.isoformat(),
        )

        assert session.calls[1][2]["json"]["timePeriod"]["from"].startswith(watermark.isoformat())

    def test_dimensions_is_a_single_get(self) -> None:
        session = _FakeSession(
            [_token_response(), _FakeResponse(200, {"value": [{"name": "ServiceName", "properties": {}}]})]
        )

        batches = _run_rows(session, "dimensions", _FakeResumeManager())

        assert batches == [
            [
                {
                    "scope": "subscriptions/abc",
                    "id": None,
                    "name": "ServiceName",
                    "type": None,
                    "category": None,
                    "description": None,
                    "filter_enabled": None,
                    "grouping_enabled": None,
                    "usage_start": None,
                    "usage_end": None,
                    "total": None,
                    "data": None,
                }
            ]
        ]
        assert session.calls[1][0] == "GET"
        assert "dimensions" in session.calls[1][1]

    def test_forecast_queries_a_forward_window(self) -> None:
        session = _FakeSession([_token_response(), _query_response([])])

        _run_rows(session, "forecast", _FakeResumeManager())

        method, url, kwargs = session.calls[1]
        assert method == "POST"
        assert "/forecast?" in url
        assert kwargs["json"]["timePeriod"]["from"].startswith(self.today.isoformat())
        assert kwargs["json"]["includeActualCost"] is False

    @parameterized.expand([("2025-03-01",), ("2026-06-01",)])
    def test_pinned_api_version_reaches_the_request_url(self, api_version: str) -> None:
        # A pinned source spends its version on every call — the query/forecast/dimensions wire is
        # identical across versions, so the only per-version difference is the api-version param.
        session = _FakeSession([_token_response(), _query_response([])])

        _run_rows(
            session,
            "cost_by_service",
            _FakeResumeManager(),
            start_date=(self.today - timedelta(days=2)).isoformat(),
            api_version=api_version,
        )

        assert f"api-version={api_version}" in session.calls[1][1]

    def test_empty_page_yields_nothing(self) -> None:
        session = _FakeSession([_token_response(), _query_response([])])

        assert (
            _run_rows(
                session,
                "cost_by_service",
                _FakeResumeManager(),
                start_date=(self.today - timedelta(days=2)).isoformat(),
            )
            == []
        )


class TestAzureCostManagementSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_matches_endpoint_settings(self, endpoint: str) -> None:
        config = AZURE_COST_MANAGEMENT_ENDPOINTS[endpoint]

        response = azure_cost_management_source(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            scope="subscriptions/abc",
            endpoint=endpoint,
            start_date=None,
            api_version="2025-03-01",
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.partition_keys == config.partition_keys
        assert response.partition_mode == config.partition_mode
        # Windows are walked oldest-first and every query is sorted ascending on UsageDate.
        assert response.sort_mode == "asc"

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_primary_key_carries_the_scope_and_day(self, endpoint: str) -> None:
        # One source syncs one scope, but the scope is still keyed so a re-pointed source cannot
        # collide rows, and the day is keyed because every dimension repeats across days.
        primary_keys = AZURE_COST_MANAGEMENT_ENDPOINTS[endpoint].primary_keys

        assert "scope" in primary_keys
        assert len(primary_keys) == len(set(primary_keys))
        if endpoint != "dimensions":
            assert "usage_date" in primary_keys
