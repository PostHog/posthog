from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.charthop import (
    CHARTHOP_BASE_URL,
    ChartHopAPIError,
    ChartHopResumeConfig,
    _to_charthop_date,
    resolve_org_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.settings import CHARTHOP_V1, CHARTHOP_V2
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source import ChartHopSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.charthop import (
    ChartHopSourceConfig,
)


def _driver(org_id: str = "org-1") -> SourceDriver:
    return SourceDriver(ChartHopSource(), ChartHopSourceConfig(api_key="key", org_id=org_id))


def _response(
    items: Optional[list[dict[str, Any]]], *, next_token: Optional[str] = None, status_code: int = 200
) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items or []}
    if next_token is not None:
        body["next"] = next_token
    return ScriptedResponse(status=status_code, json=body)


class TestToChartHopDate:
    @parameterized.expand(
        [
            ("date", date(2026, 1, 15), "2026-01-15"),
            ("aware_datetime", datetime(2026, 1, 15, 12, 30, tzinfo=UTC), "2026-01-15"),
            ("naive_datetime", datetime(2026, 1, 15, 12, 30), "2026-01-15"),
            ("date_string", "2026-01-15", "2026-01-15"),
            ("datetime_string", "2026-01-15T12:30:00Z", "2026-01-15"),
            ("garbage_string", "not-a-date", None),
            ("non_date_type", 12345, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: Optional[str]) -> None:
        assert _to_charthop_date(value) == expected

    def test_future_date_clamped_to_today(self) -> None:
        future = date.today().replace(year=date.today().year + 1)
        assert _to_charthop_date(future) == datetime.now(UTC).date().isoformat()


class TestPagination:
    def test_org_id_is_encoded_as_single_path_segment(self) -> None:
        result = _driver("org/../evil?x=1").run("jobs", [_response([])])

        assert result.raised is None
        assert result.urls[0].split("?", 1)[0] == f"{CHARTHOP_BASE_URL}/v2/org/org%2F..%2Fevil%3Fx%3D1/job"

    def test_saves_state_after_yielding_each_page(self) -> None:
        result = _driver().run("jobs", [_response([{"id": "1"}], next_token="1"), _response([{"id": "2"}])])

        assert result.raised is None
        assert result.rows == [{"id": "1"}, {"id": "2"}]
        assert result.saved_states == [ChartHopResumeConfig(from_token="1", start_date=None)]

    def test_resumes_from_saved_cursor_and_start_date(self) -> None:
        result = _driver().run(
            "changes",
            [_response([{"id": "9"}])],
            resume_state=ChartHopResumeConfig(from_token="8", start_date="2026-01-01"),
            should_use_incremental_field=True,
            # The saved window must win over the advanced watermark on resume.
            db_incremental_field_last_value=date(2026, 2, 1),
            api_version=CHARTHOP_V1,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["9"]
        assert result.requests[0].param("from") == "8"
        assert result.requests[0].param("date") == "2026-01-01"

    def test_incremental_date_filter_sent_on_every_page(self) -> None:
        result = _driver().run(
            "changes",
            [_response([{"id": "1"}], next_token="1"), _response([{"id": "2"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 1, 15),
            api_version=CHARTHOP_V1,
        )

        assert result.raised is None
        assert result.params("date") == ["2026-01-15", "2026-01-15"]

    @parameterized.expand(
        [
            (CHARTHOP_V1, "/v1/org/org-1/change", "date"),
            (CHARTHOP_V2, "/v2/org/org-1/change", "fromDate"),
        ]
    )
    def test_changes_endpoint_dispatches_path_and_filter_by_version(
        self, version: str, expected_path: str, expected_param: str
    ) -> None:
        result = _driver().run(
            "changes",
            [_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 1, 15),
            api_version=version,
        )

        assert result.raised is None
        assert result.paths[0] == expected_path
        assert result.requests[0].param(expected_param) == "2026-01-15"

    @parameterized.expand(
        [
            ("jobs", "jobs"),
            ("time_off_policies", "time_off_policies"),
            ("comp_bands", "comp_bands"),
            # compensation-history does accept a startDate filter, but only serves descending
            # rows, so it stays full refresh — a watermark must never reach the request.
            ("compensation_history", "compensation_history"),
        ]
    )
    def test_full_refresh_endpoint_never_sends_date_filter(self, _name: str, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 1, 15),
        )

        assert result.raised is None
        assert not {"date", "fromDate", "startDate"} & set(result.queries[0])

    @parameterized.expand(
        [
            # Ex-employees, so departures stay queryable.
            ("persons", "persons", "includeAll"),
            # Retired bands, so jobs referencing them stay resolvable.
            ("comp_bands", "comp_bands", "includeDeleted"),
        ]
    )
    def test_static_params_sent_on_every_page(self, _name: str, endpoint: str, param: str) -> None:
        result = _driver().run(endpoint, [_response([{"id": "1"}], next_token="1"), _response([{"id": "2"}])])

        assert result.raised is None
        assert result.params(param) == ["true", "true"]

    @parameterized.expand(
        [
            ("time_off_policies", "time_off_policies", "/v1/org/org-1/timeoff/policy"),
            ("comp_bands", "comp_bands", "/v1/org/org-1/band"),
            ("compensation_history", "compensation_history", "/v1/org/org-1/change/compensation-history"),
        ]
    )
    def test_endpoints_without_a_v2_path_stay_on_v1_under_the_v2_pin(
        self, _name: str, endpoint: str, expected_path: str
    ) -> None:
        # ChartHop only serves these under /v1, so the default v2 pin must fall through to the
        # base path rather than rewriting the version segment.
        result = _driver().run(endpoint, [_response([])], api_version=CHARTHOP_V2)

        assert result.raised is None
        assert result.paths[0] == expected_path

    @parameterized.expand([(401,), (403,)])
    def test_http_auth_errors_raise_matchable_error(self, status_code: int) -> None:
        result = _driver().run("jobs", [_response([], status_code=status_code)])

        assert isinstance(result.raised, HTTPError)
        assert f"{status_code} Client Error" in str(result.raised)


class TestResolveOrgId:
    @parameterized.expand([("plain", "org-1"), ("padded", "  org-1  ")])
    def test_configured_org_id_skips_lookup(self, _name: str, configured: str) -> None:
        with scripted_network([]) as network:
            assert resolve_org_id("key", configured) == "org-1"
        assert network.requests_log == []

    def test_single_org_auto_detected(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": [{"id": "org-9"}]})]) as network:
            assert resolve_org_id("key", None) == "org-9"

        assert network.requests_log[0].path == "/v1/org"
        assert network.requests_log[0].param("limit") == "2"

    @parameterized.expand(
        [
            ("no_orgs", [], "has no access to any organization"),
            ("multiple_orgs", [{"id": "a"}, {"id": "b"}], "can access multiple organizations"),
        ]
    )
    def test_zero_or_multiple_orgs_raise(self, _name: str, orgs: list[dict[str, Any]], expected_message: str) -> None:
        with scripted_network([ScriptedResponse(json={"data": orgs})]):
            with pytest.raises(ChartHopAPIError) as exc:
                resolve_org_id("key", "")
        assert expected_message in str(exc.value)

    def test_auth_error_raises_matchable_api_error(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]):
            with pytest.raises(ChartHopAPIError) as exc:
                resolve_org_id("key", None)
        assert "401 Client Error" in str(exc.value)
