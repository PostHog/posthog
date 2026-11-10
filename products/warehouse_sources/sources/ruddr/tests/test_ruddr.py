import datetime as dt
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.sources.ruddr._config import RuddrSourceConfig
from products.warehouse_sources.sources.ruddr.ruddr import PAGE_SIZE, RuddrResumeConfig
from products.warehouse_sources.sources.ruddr.settings import ENDPOINTS, RUDDR_ENDPOINTS
from products.warehouse_sources.sources.ruddr.source import RuddrSource
from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always


def _response(results: list[dict[str, Any]], *, has_more: bool = False, status_code: int = 200) -> ScriptedResponse:
    # Ruddr list endpoints wrap records in {"results": [...], "hasMore": bool}.
    return ScriptedResponse(status=status_code, json={"results": results, "hasMore": has_more})


def _driver() -> SourceDriver:
    return SourceDriver(RuddrSource(), RuddrSourceConfig(api_key="key"))


def _full_page(start_id: int) -> list[dict[str, Any]]:
    # Ruddr resource ids are strings, and the cursor (RuddrResumeConfig.cursor) is typed str | None.
    return [{"id": str(start_id + i)} for i in range(PAGE_SIZE)]


class TestPagination:
    def test_follows_cursor_until_hasmore_false(self) -> None:
        # First page is full with hasMore true; the cursor advances to the last row's id ("99").
        result = _driver().run(
            "clients", [_response(_full_page(0), has_more=True), _response([{"id": "999"}], has_more=False)]
        )

        assert [r["id"] for r in result.rows] == [*(str(i) for i in range(PAGE_SIZE)), "999"]
        # First page has limit only; the second carries startingAfter = the previous page's last id.
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),)}
        assert result.queries[1] == {"limit": (str(PAGE_SIZE),), "startingAfter": (str(PAGE_SIZE - 1),)}
        # Checkpoint saved after the first page (points at the next page); hasMore false ends it.
        assert result.saved_states == [RuddrResumeConfig(cursor=str(PAGE_SIZE - 1))]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "clients", [_response([{"id": "5"}], has_more=False)], resume_state=RuddrResumeConfig(cursor="cur-99")
        )

        assert [r["id"] for r in result.rows] == ["5"]
        # The initial (cursor-less) page must never be fetched on resume — the first request
        # targets the saved cursor.
        assert result.params("startingAfter")[0] == "cur-99"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("clients", [_response([{"id": "5"}], has_more=False)])

        assert result.params("startingAfter") == [None]

    @parameterized.expand(
        [
            ("time_entries", "https://www.ruddr.io/api/workspace/time-entries"),
            ("project_tasks", "https://www.ruddr.io/api/workspace/project-tasks"),
            ("project_prepayments", "https://www.ruddr.io/api/workspace/project-prepayments"),
            ("timesheet_attestations", "https://www.ruddr.io/api/workspace/timesheet-attestations"),
            ("task_categories", "https://www.ruddr.io/api/workspace/task-categories"),
            ("pipeline_activities", "https://www.ruddr.io/api/workspace/pipeline-activities"),
            ("project_roles", "https://www.ruddr.io/api/workspace/project-roles"),
            ("invoices", "https://www.ruddr.io/api/workspace/invoices"),
            ("invoice_items", "https://www.ruddr.io/api/workspace/invoice-items"),
            ("allocations", "https://www.ruddr.io/api/workspace/allocations"),
            ("project_members", "https://www.ruddr.io/api/workspace/project-members"),
            ("opportunities", "https://www.ruddr.io/api/workspace/opportunities"),
            ("opportunity_stages", "https://www.ruddr.io/api/workspace/opportunity-stages"),
            ("project_health_reports", "https://www.ruddr.io/api/workspace/project-health-reports"),
        ]
    )
    def test_request_targets_endpoint_path(self, endpoint: str, expected_url: str) -> None:
        # Schema names use underscores but Ruddr's paths use hyphens; assert each declared path
        # reaches the hyphenated URL rather than a 404.
        result = _driver().run(endpoint, [_response([{"id": "1"}], has_more=False)])

        assert result.urls[0].split("?")[0] == expected_url


class TestIncrementalRequests:
    @parameterized.expand(
        [
            (
                "datetime_watermark",
                True,
                dt.datetime(2025, 2, 5, 20, 47, 3, 284000, tzinfo=dt.UTC),
                "2025-02-05T20:47:03.284Z",
            ),
            ("naive_datetime_watermark", True, dt.datetime(2025, 2, 5, 20, 47, 3), "2025-02-05T20:47:03.000Z"),
            ("string_watermark", True, "2025-02-05T20:47:03.284Z", "2025-02-05T20:47:03.284Z"),
            ("first_incremental_sync", True, None, None),
            ("full_refresh_ignores_watermark", False, dt.datetime(2025, 2, 5, tzinfo=dt.UTC), None),
        ]
    )
    def test_invoices_filter_on_modified_at_on_every_page(
        self, _name: str, use_incremental: bool, last_value: Any, expected_filter: str | None
    ) -> None:
        result = _driver().run(
            "invoices",
            [_response(_full_page(0), has_more=True), _response([{"id": "999"}], has_more=False)],
            should_use_incremental_field=use_incremental,
            incremental_field="modifiedAt" if use_incremental else None,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        # The filter must stay on the cursor page too, or later pages walk back through all history.
        assert result.params("modifiedAtOnAfter") == [expected_filter, expected_filter]
        assert result.params("startingAfter") == [None, str(PAGE_SIZE - 1)]

    def test_allocations_reject_modified_at_filter(self) -> None:
        # Derived allocations have a null modifiedAt, so a modifiedAt filter would silently drop them.
        result = _driver().run(
            "allocations",
            always(_response([])),
            should_use_incremental_field=True,
            incremental_field="modifiedAt",
            db_incremental_field_last_value=dt.datetime(2025, 2, 5, tzinfo=dt.UTC),
        )

        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestErrorHandling:
    def test_non_dict_body_is_retried_then_reraises(self) -> None:
        # A 200 body that is a bare array (not the {"results": [...]} envelope) — retried, never
        # ingested as rows.
        result = _driver().run("clients", always(ScriptedResponse(json=[{"id": "1"}])))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert "Unexpected 200 response body shape" in str(result.raised)
        assert result.rows == []
        # Retried before giving up.
        assert len(result.requests) > 1

    def test_missing_results_key_is_retried_then_reraises(self) -> None:
        result = _driver().run("clients", always(ScriptedResponse(json={"hasMore": False})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert "Unexpected 200 response body shape" in str(result.raised)
        assert len(result.requests) > 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_then_success_recovers(self, _name, status) -> None:
        result = _driver().run("clients", [_response([], status_code=status), _response([{"id": "1"}], has_more=False)])

        assert [r["id"] for r in result.rows] == ["1"]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name, status) -> None:
        result = _driver().run("clients", always(_response([], status_code=status)))

        assert isinstance(result.raised, HTTPError)


class TestRuddrSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(_response([])))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in RUDDR_ENDPOINTS.values())
        assert set(RUDDR_ENDPOINTS) == set(ENDPOINTS)
