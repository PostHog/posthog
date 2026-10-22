from datetime import UTC, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualaroo import (
    QualarooSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.qualaroo import (
    PAGE_SIZE,
    QualarooResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.settings import (
    ENDPOINTS,
    QUALAROO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source import QualarooSource


def _driver() -> SourceDriver:
    return SourceDriver(QualarooSource(), QualarooSourceConfig(api_key="q-key", api_secret="q-secret"))


def _run(script: Script, **inputs: Any) -> DriveResult:
    return _driver().run("nudges", script, **inputs)


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        result = _run([ScriptedResponse(json=_full_page(0)), ScriptedResponse(json=[{"id": 999}])])

        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1] == {"id": 999}
        # First request starts at offset 0 with the max page size; second advances one page.
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [QualarooResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        # Offset 0 must never be fetched on resume — the first request starts at the saved offset.
        result = _run([ScriptedResponse(json=[{"id": 5}])], resume_state=QualarooResumeConfig(offset=PAGE_SIZE))

        assert result.rows == [{"id": 5}]
        assert result.params("offset") == [str(PAGE_SIZE)]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _run([ScriptedResponse(json=[{"id": 5}])])

        assert result.params("offset") == ["0"]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_retried_then_reraised(self, _name: str, status: int) -> None:
        result = _run(always(ScriptedResponse(status=status, json=[])))

        assert isinstance(result.raised, RESTClientRetryableError)
        # A persistent retryable status is reissued, not surfaced on the first attempt.
        assert len(result.requests) > 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_fail_loud_without_retry(self, _name: str, status: int) -> None:
        result = _run([ScriptedResponse(status=status, json={"error": "nope"})])

        assert isinstance(result.raised, requests.HTTPError)
        # 4xx is permanent — the request must not be reissued.
        assert len(result.requests) == 1

    def test_non_list_body_is_retried(self) -> None:
        # Qualaroo list endpoints return a bare array; a 200 dict body is treated as a transient
        # shape glitch and reissued rather than ingested as a single row.
        result = _run(always(ScriptedResponse(json={"error": "nope"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
        ]
    )
    def test_status_mapping(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json=[]))) as network:
            assert validate_credentials("q-key", "q-secret") == (expected_valid, expected_message)

        assert network.requests_log[0].path == "/api/v1/nudges.json"
        assert network.requests_log[0].param("limit") == "1"


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == QUALAROO_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert result.response.partition_mode is None


class TestResponsesFanOut:
    def test_walks_every_nudge_and_every_response_page(self) -> None:
        result = _driver().run(
            "responses",
            route(
                {
                    "/nudges.json": [ScriptedResponse(json=[{"id": 11}, {"id": 22}, {"id": 33}])],
                    "/nudges/11/responses.json": [
                        ScriptedResponse(
                            json=[{"id": i, "time": "2024-03-01 10:00:00 -0700"} for i in range(PAGE_SIZE)]
                        ),
                        ScriptedResponse(json=[{"id": 900, "answered_questions": {}, "properties": None}]),
                    ],
                    "/nudges/22/responses.json": [ScriptedResponse(status=404, json={"error": "Not Found"})],
                    "/nudges/33/responses.json": [ScriptedResponse(json=[{"id": 1}])],
                }
            ),
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 2
        assert result.rows[PAGE_SIZE] == {"id": 900, "answered_questions": {}, "properties": None, "nudge_id": 11}
        # Response ids are keyed with their nudge, so the same id under two nudges stays two rows.
        assert {(row["nudge_id"], row["id"]) for row in result.rows if row["id"] == 1} == {(11, 1), (33, 1)}
        assert [(request.path, request.param("offset")) for request in result.requests] == [
            ("/api/v1/nudges.json", "0"),
            ("/api/v1/nudges/11/responses.json", "0"),
            ("/api/v1/nudges/11/responses.json", str(PAGE_SIZE)),
            ("/api/v1/nudges/22/responses.json", "0"),
            ("/api/v1/nudges/33/responses.json", "0"),
        ]
        child_requests = [request for request in result.requests if request.path.endswith("/responses.json")]
        assert {request.param("order") for request in child_requests} == {"asc"}
        assert {request.param("limit") for request in result.requests} == {str(PAGE_SIZE)}

    @parameterized.expand(
        [
            ("full_refresh", {"should_use_incremental_field": False}, None),
            ("first_incremental_run", {"incremental_field": "time"}, None),
            (
                "watermark_string_with_offset",
                {"incremental_field": "time", "db_incremental_field_last_value": "2024-03-01 10:00:00 -0700"},
                str(int(datetime(2024, 3, 1, 17, 0, 0, tzinfo=UTC).timestamp()) - 1),
            ),
            (
                "watermark_naive_datetime_is_utc",
                {"incremental_field": "time", "db_incremental_field_last_value": datetime(2024, 3, 1, 17, 0, 0)},
                str(int(datetime(2024, 3, 1, 17, 0, 0, tzinfo=UTC).timestamp()) - 1),
            ),
        ]
    )
    def test_start_date_follows_the_watermark(
        self, _name: str, inputs: dict[str, Any], expected_start_date: str | None
    ) -> None:
        result = _driver().run(
            "responses",
            route(
                {
                    "/nudges.json": [ScriptedResponse(json=[{"id": 11}])],
                    "/nudges/11/responses.json": [ScriptedResponse(json=[{"id": 1}])],
                }
            ),
            **inputs,
        )

        assert result.raised is None
        assert [request.param("start_date") for request in result.requests] == [None, expected_start_date]
        end_dates = [request.param("end_date") for request in result.requests]
        assert end_dates[0] is None
        assert (end_dates[1] is not None) == inputs.get("should_use_incremental_field", True)

    def test_resumed_incremental_sync_keeps_the_original_end_date(self) -> None:
        sync_end = "2024-03-02T00:00:00+00:00"
        result = _driver().run(
            "responses",
            route(
                {
                    "/nudges.json": [ScriptedResponse(json=[{"id": 11}, {"id": 22}])],
                    "/nudges/22/responses.json": [ScriptedResponse(json=[{"id": 7, "time": "2024-03-01 10:00:00"}])],
                }
            ),
            resume_state=QualarooResumeConfig(
                fanout_state={"completed": ["/nudges/11/responses.json"], "current": None, "child_state": None},
                sync_end=sync_end,
            ),
            incremental_field="time",
            db_incremental_field_last_value="2024-03-01 00:00:00",
        )

        assert result.raised is None
        child_requests = [request for request in result.requests if request.path.endswith("/responses.json")]
        expected_end_date = str(int(datetime(2024, 3, 2, tzinfo=UTC).timestamp()) - 1)
        assert [request.param("end_date") for request in child_requests] == [expected_end_date]
        assert all(state.sync_end == sync_end for state in result.saved_states)

    def test_resumes_inside_the_nudge_in_progress(self) -> None:
        result = _driver().run(
            "responses",
            route(
                {
                    "/nudges.json": [ScriptedResponse(json=[{"id": 11}, {"id": 22}, {"id": 33}])],
                    "/nudges/22/responses.json": [ScriptedResponse(json=[{"id": 7}])],
                    "/nudges/33/responses.json": [ScriptedResponse(json=[])],
                }
            ),
            resume_state=QualarooResumeConfig(
                fanout_state={
                    "completed": ["/nudges/11/responses.json"],
                    "current": "/nudges/22/responses.json",
                    "child_state": {"offset": PAGE_SIZE},
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": 7, "nudge_id": 22}]
        assert [(request.path, request.param("offset")) for request in result.requests] == [
            ("/api/v1/nudges.json", "0"),
            ("/api/v1/nudges/22/responses.json", str(PAGE_SIZE)),
            ("/api/v1/nudges/33/responses.json", "0"),
        ]
