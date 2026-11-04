from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.sources.salesloft._config import SalesLoftSourceConfig
from products.warehouse_sources.sources.salesloft.salesloft import (
    SALESLOFT_BASE_URL,
    SalesloftResumeConfig,
    _build_params,
    _format_datetime,
    validate_credentials,
)
from products.warehouse_sources.sources.salesloft.settings import SALESLOFT_ENDPOINTS
from products.warehouse_sources.sources.salesloft.source import SalesLoftSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)


def _response(items: list[dict[str, Any]] | None, next_page: int | None, status: int = 200) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items or [], "metadata": {"paging": {"per_page": 100, "next_page": next_page}}}
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(SalesLoftSource(), SalesLoftSourceConfig(api_key="sl_token"))


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        result = _format_datetime(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_falls_back_to_updated_at_when_field_missing(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["accounts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=None,
        )
        assert "updated_at[gte]" in params


class TestIncrementalRequestShaping:
    @pytest.mark.parametrize(
        "endpoint, expected_sort_by",
        [
            # Their default sort keys (due_date, occurred_at) would break the ascending watermark.
            ("tasks", "updated_at"),
            ("activity_histories", "updated_at"),
            ("opportunities", "updated_at"),
            # Endpoints whose default sort key is already updated_at send no sort_by.
            ("people", None),
        ],
    )
    def test_incremental_run_sorts_and_filters_on_updated_at(self, endpoint: str, expected_sort_by: str | None) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": 1}], next_page=None)],
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("sort_by") == expected_sort_by
        assert result.requests[0].param("sort_direction") == "ASC"
        assert result.requests[0].param("updated_at[gte]") == "2026-03-04T02:58:14.000Z"


def _stats(sent: int) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"sent_emails_count": sent, "replied_rate": "40.0%"}})


class TestCadenceStatsFanout:
    def test_walks_every_cadence_page_and_tags_stats_with_the_cadence_id(self) -> None:
        script = route(
            {
                "/cadences": [
                    _response([{"id": 1}, {"id": 2}], next_page=2),
                    _response([{"id": 3}], next_page=None),
                ],
                "/cadence_stats/1": [_stats(10)],
                # Cadence deleted between the listing and the stats fetch.
                "/cadence_stats/2": [ScriptedResponse(status=404, json={"error": "Not Found"})],
                "/cadence_stats/3": [_stats(30)],
            }
        )

        result = _driver().run("cadence_stats", script)

        assert result.raised is None
        assert [(row["cadence_id"], row["sent_emails_count"]) for row in result.rows] == [(1, 10), (3, 30)]
        assert all("_cadences_id" not in row for row in result.rows)
        assert result.paths == [
            "/v2/cadences",
            "/v2/cadence_stats/1",
            "/v2/cadence_stats/2",
            "/v2/cadences",
            "/v2/cadence_stats/3",
        ]
        parent_requests = [r for r in result.requests if r.path == "/v2/cadences"]
        assert [r.param("page") for r in parent_requests] == [None, "2"]
        assert all(r.param("sort_by") == "created_at" and r.param("per_page") == "100" for r in parent_requests)
        assert all(r.param("per_page") is None for r in result.requests if r.path.startswith("/v2/cadence_stats/"))

    def test_resume_skips_cadences_already_synced(self) -> None:
        cadences = _response([{"id": 1}, {"id": 2}], next_page=None)
        first = _driver().run(
            "cadence_stats",
            route(
                {
                    "/cadences": [cadences],
                    "/cadence_stats/1": [_stats(10)],
                    "/cadence_stats/2": [ScriptedResponse(status=401, json={"error": "Unauthorized"})],
                }
            ),
        )
        assert isinstance(first.raised, requests.HTTPError)
        assert first.final_state is not None

        resumed = _driver().run(
            "cadence_stats",
            route({"/cadences": [cadences], "/cadence_stats/2": [_stats(20)]}),
            resume_state=first.final_state,
        )

        assert resumed.raised is None
        assert [(row["cadence_id"], row["sent_emails_count"]) for row in resumed.rows] == [(2, 20)]
        assert "/v2/cadence_stats/1" not in resumed.paths


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("sl_token") is expected

        request = network.requests_log[0]
        assert request.url == f"{SALESLOFT_BASE_URL}/me"
        assert request.headers["authorization"] == "Bearer sl_token"


class TestPagination:
    def test_paginates_until_next_page_is_null(self) -> None:
        result = _driver().run(
            "people", [_response([{"id": 1}, {"id": 2}], next_page=2), _response([{"id": 3}], next_page=None)]
        )

        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert len(result.requests) == 2
        # First request carries the static params; the next page rides the `page` cursor.
        assert result.requests[0].param("per_page") == "100"
        assert result.requests[0].param("page") is None
        assert result.requests[1].param("page") == "2"

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "people", [_response([{"id": 9}], next_page=None)], resume_state=SalesloftResumeConfig(next_page=5)
        )

        assert [row["id"] for row in result.rows] == [9]
        assert result.requests[0].param("page") == "5"

    def test_resumes_from_legacy_next_url_state(self) -> None:
        legacy = SalesloftResumeConfig(next_url=f"{SALESLOFT_BASE_URL}/people?per_page=100&page=7")

        result = _driver().run("people", [_response([{"id": 9}], next_page=None)], resume_state=legacy)

        assert result.requests[0].param("page") == "7"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("people", [_response([{"id": 9}], next_page=None)])

        assert result.requests[0].param("page") is None

    def test_non_retryable_status_raises(self) -> None:
        result = _driver().run("people", [_response(None, next_page=None, status=404)])

        assert isinstance(result.raised, requests.HTTPError)


class TestSalesloftSource:
    def test_partition_key_is_always_created_at_never_updated_at(self) -> None:
        for config in SALESLOFT_ENDPOINTS.values():
            assert config.partition_key in (None, "created_at")
