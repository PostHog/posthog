import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instana import (
    InstanaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instana import instana as inst
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.instana import (
    InstanaResumeConfig,
    _to_epoch_ms,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.settings import (
    APDEX_REPORT_WINDOW_MS,
    EVENTS_DEFAULT_LOOKBACK_DAYS,
    EVENTS_WINDOW_CHUNK_MS,
    METRICS_WINDOW_MS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.source import InstanaSource

BASE_URL = "https://unit-tenant.instana.io"


DRIVER = SourceDriver(InstanaSource(), InstanaSourceConfig(base_url=BASE_URL, api_token="token"))


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://unit-tenant.instana.io", "https://unit-tenant.instana.io"),
            ("unit-tenant.instana.io", "https://unit-tenant.instana.io"),
            ("  https://unit-tenant.instana.io/  ", "https://unit-tenant.instana.io"),
            # http is upgraded so the token never travels in plaintext.
            ("http://selfhosted.example.com", "https://selfhosted.example.com"),
            # Paths/queries are dropped so endpoint paths always join against the bare host.
            ("https://unit-tenant.instana.io/some/path?q=1", "https://unit-tenant.instana.io"),
            ("https://selfhosted.example.com:8443", "https://selfhosted.example.com:8443"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert normalize_base_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "https://",
            "ftp://unit-tenant.instana.io",
            # Embedded credentials could smuggle the request elsewhere.
            "https://user:pass@evil.example.com",
        ],
    )
    def test_rejects_invalid(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_base_url(raw)


class TestToEpochMs:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1767225600000, 1767225600000),
            (1767225600000.0, 1767225600000),
            ("1767225600000", 1767225600000),
            (datetime(2026, 1, 1, tzinfo=UTC), 1767225600000),
            (datetime(2026, 1, 1), 1767225600000),  # naive treated as UTC
            (date(2026, 1, 1), 1767225600000),
            ("not-a-number", None),
            (None, None),
            (True, None),
        ],
    )
    def test_coercion(self, value: Any, expected: int | None) -> None:
        assert _to_epoch_ms(value) == expected


def _run_get_rows(
    endpoint: str,
    pages: list[Any],
    resume_state: InstanaResumeConfig | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> DriveResult:
    result = DRIVER.run(
        endpoint,
        [ScriptedResponse(json=page) for page in pages],
        resume_state=resume_state,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )
    assert result.raised is None
    return result


class TestEventRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-01-10T00:00:00Z", tick=False):
            yield

    NOW_MS = 1768003200000

    def test_incremental_run_chunks_from_watermark(self) -> None:
        watermark = self.NOW_MS - int(1.5 * EVENTS_WINDOW_CHUNK_MS)
        pages = [[{"eventId": "a", "start": watermark + 1}]] * 2
        result = _run_get_rows(
            "events",
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert len(result.requests) == 2
        first, second = result.requests
        assert first.param("from") == str(watermark)
        assert first.param("to") == str(watermark + EVENTS_WINDOW_CHUNK_MS)
        assert second.param("from") == str(watermark + EVENTS_WINDOW_CHUNK_MS)
        assert second.param("to") == str(self.NOW_MS)
        # Both chunks yielded rows.
        assert len(result.items) == 2
        # State saved only between chunks (after the yield), never after the final chunk.
        assert result.saved_states == [InstanaResumeConfig(events_window_from=watermark + EVENTS_WINDOW_CHUNK_MS)]
        assert result.committed_states == [InstanaResumeConfig(events_window_from=watermark + EVENTS_WINDOW_CHUNK_MS)]

    def test_first_sync_reaches_back_the_default_lookback(self) -> None:
        result = _run_get_rows("events", [[] for _ in range(EVENTS_DEFAULT_LOOKBACK_DAYS)])

        expected_from = self.NOW_MS - EVENTS_DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000
        assert result.requests[0].param("from") == str(expected_from)
        assert result.requests[-1].param("to") == str(self.NOW_MS)
        assert len(result.requests) == EVENTS_DEFAULT_LOOKBACK_DAYS
        # Empty windows keep advancing without yielding.
        assert result.rows == []

    def test_resume_starts_at_saved_window(self) -> None:
        resume_from = self.NOW_MS - EVENTS_WINDOW_CHUNK_MS // 2
        result = _run_get_rows(
            "events",
            [[]],
            resume_state=InstanaResumeConfig(events_window_from=resume_from),
        )

        assert len(result.requests) == 1
        assert result.requests[0].param("from") == str(resume_from)


class TestPagedRows:
    def _page(self, count: int, page: int, total_hits: int) -> dict[str, Any]:
        return {"items": [{"id": f"p{page}-{i}"} for i in range(count)], "page": page, "totalHits": total_hits}

    def test_total_hits_terminates_a_full_final_page(self) -> None:
        pages = [self._page(PAGE_SIZE, page=1, total_hits=PAGE_SIZE)]
        result = _run_get_rows("endpoints", pages)

        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resume_starts_at_saved_page(self) -> None:
        pages = [self._page(2, page=5, total_hits=1000)]
        result = _run_get_rows("applications", pages, resume_state=InstanaResumeConfig(next_page=5))

        assert result.requests[0].param("page") == "5"

    def test_pagination_limit_aborts_runaway_walk(self) -> None:
        # A self-hosted host can return a full page forever while omitting a reliable totalHits, so
        # the normal termination conditions never trip; the walk must abort past MAX_CATALOG_PAGES.
        full_page = self._page(PAGE_SIZE, page=1, total_hits=10**9)
        with mock.patch.object(inst, "MAX_CATALOG_PAGES", 3):
            result = DRIVER.run("applications", always(ScriptedResponse(json=full_page)))

        assert isinstance(result.raised, inst.InstanaPaginationLimitError)
        assert len(result.requests) == 3

    def test_pagination_walk_stops_at_time_budget(self) -> None:
        # A slow host can stay under the per-page limits (and the page cap) while holding the worker,
        # so the walk must also stop on a cumulative wall-clock budget.
        full_page = self._page(PAGE_SIZE, page=1, total_hits=10**9)

        def slow_page(_request: RecordedRequest) -> ScriptedResponse:
            time.sleep(2)
            return ScriptedResponse(json=full_page)

        with mock.patch.object(inst, "MAX_CATALOG_WALK_SECONDS", 5):
            result = DRIVER.run("applications", slow_page)

        assert isinstance(result.raised, inst.InstanaPaginationLimitError)
        assert len(result.requests) == 3


class TestOffsetRows:
    @staticmethod
    def _page(n: int, start: int = 0) -> list[dict[str, Any]]:
        return [{"testResultId": f"r{start + i}"} for i in range(n)]

    def test_walks_offsets_until_short_page(self) -> None:
        pages = [self._page(PAGE_SIZE), self._page(3, start=PAGE_SIZE)]
        result = _run_get_rows("synthetic_test_ci_cds", pages)

        assert result.params("offset") == ["0", "1"]
        assert result.params("limit") == [str(PAGE_SIZE)] * 2
        assert result.saved_states == [InstanaResumeConfig(next_offset=1)]
        assert len(result.rows) == PAGE_SIZE + 3

    def test_resume_starts_at_saved_offset(self) -> None:
        result = _run_get_rows(
            "synthetic_test_ci_cds",
            [self._page(1)],
            resume_state=InstanaResumeConfig(next_offset=2),
        )

        assert result.requests[0].param("offset") == "2"


def _run_metric_rows(
    endpoint: str,
    pages: list[Any],
    resume_state: InstanaResumeConfig | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> DriveResult:
    result = DRIVER.run(
        endpoint,
        [ScriptedResponse(json=page) for page in pages],
        resume_state=resume_state,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )
    assert result.raised is None
    return result


class TestMetricRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-01-10T15:30:00Z", tick=False):
            yield

    # 2026-01-10T00:00:00Z: the last complete day ends here.
    TODAY_MS = 1768003200000

    def test_items_are_pivoted_into_a_row_per_entity_and_timestamp(self) -> None:
        service = {"id": "svc1", "label": "checkout"}
        page = {
            "items": [
                {
                    "service": service,
                    "metrics": {"calls.sum": [[100, 7], [200, 9]], "latency.p90": [[100, 12.5]]},
                },
                # Items without an entity id can't be keyed, so they are dropped.
                {"service": {"label": "orphan"}, "metrics": {"calls.sum": [[100, 1]]}},
            ],
            "totalHits": 2,
        }
        result = _run_metric_rows(
            "service_metrics", [page], should_use_incremental_field=True, db_incremental_field_last_value=self.TODAY_MS
        )

        assert result.rows == [
            {"serviceId": "svc1", "service": service, "timestamp": 100, "calls_sum": 7, "latency_p90": 12.5},
            {"serviceId": "svc1", "service": service, "timestamp": 200, "calls_sum": 9},
        ]

    def test_paginates_within_a_window_and_resumes_from_saved_page(self) -> None:
        full = {"items": [{"application": {"id": f"a{i}"}, "metrics": {}} for i in range(PAGE_SIZE)], "totalHits": 999}
        last = {"items": [{"application": {"id": "z"}, "metrics": {"calls.sum": [[1, 1]]}}], "totalHits": 999}
        window_from = self.TODAY_MS - METRICS_WINDOW_MS

        result = _run_metric_rows("application_metrics", [full, *([last] * 7)])
        assert [request.json()["pagination"]["page"] for request in result.requests[:2]] == [1, 2]
        assert (
            InstanaResumeConfig(metrics_window_from=self.TODAY_MS - 7 * METRICS_WINDOW_MS, next_page=2)
            in result.saved_states
        )

        result = _run_metric_rows(
            "application_metrics",
            [last],
            resume_state=InstanaResumeConfig(metrics_window_from=window_from, next_page=3),
        )
        assert len(result.requests) == 1
        assert result.requests[0].json()["pagination"]["page"] == 3
        assert result.requests[0].json()["timeFrame"]["to"] == self.TODAY_MS
        assert result.items == [[{"applicationId": "z", "application": {"id": "z"}, "timestamp": 1, "calls_sum": 1}]]


class TestFanOutRows:
    @staticmethod
    def _script(reports: dict[str, Any]) -> list[ScriptedResponse]:
        return [
            ScriptedResponse(json={"items": [{"id": slo_id} for slo_id in reports], "page": 1, "totalHits": 2}),
            *[
                ScriptedResponse(status=404, json={"message": "not found"})
                if report is None
                else ScriptedResponse(json=report)
                for report in reports.values()
            ],
        ]

    @pytest.mark.parametrize(
        "report_body",
        [
            {"sli": 0.99, "fromTimestamp": 1},
            [{"sli": 0.99, "fromTimestamp": 1}],
        ],
    )
    def test_reports_carry_parent_id_and_deleted_parent_is_skipped(self, report_body: Any) -> None:
        result = DRIVER.run("slo_reports", self._script({"SLO1": report_body, "SLO_GONE": None, "SLO2": report_body}))

        assert result.raised is None
        assert result.paths[1:] == [
            "/api/slo/report/SLO1",
            "/api/slo/report/SLO_GONE",
            "/api/slo/report/SLO2",
        ]
        assert result.items == [
            [{"sli": 0.99, "fromTimestamp": 1, "sloId": "SLO1"}],
            [{"sli": 0.99, "fromTimestamp": 1, "sloId": "SLO2"}],
        ]

    def test_child_requests_count_against_the_walk_bounds(self) -> None:
        # One parent page can hold many slow child requests; the bound must trip inside the page,
        # not only when the parent walk asks for its next page.
        with mock.patch.object(inst, "MAX_CATALOG_PAGES", 1):
            result = DRIVER.run("slo_reports", self._script({"SLO1": {"sli": 1}, "SLO2": {"sli": 1}}))

        assert isinstance(result.raised, inst.InstanaPaginationLimitError)
        assert result.paths == ["/api/settings/slo", "/api/slo/report/SLO1"]

    @time_machine.travel("2026-01-10T00:00:00Z", tick=False)
    def test_apdex_reports_request_a_trailing_window(self) -> None:
        result = DRIVER.run(
            "apdex_reports",
            [
                ScriptedResponse(json=[{"id": "APDEX1"}]),
                ScriptedResponse(json=[{"apdexId": "APDEX1", "apdexScore": [[1, 0.9]], "from": 1, "to": 2}]),
            ],
        )

        assert result.raised is None
        assert result.paths[1] == "/api/apdex/report/APDEX1"
        now_ms = 1768003200000
        assert result.queries[1] == {
            "from": (str(now_ms - APDEX_REPORT_WINDOW_MS),),
            "to": (str(now_ms),),
        }
        assert result.items == [[{"apdexId": "APDEX1", "apdexScore": [[1, 0.9]], "from": 1, "to": 2}]]


class TestListRows:
    def test_bare_list_body_is_yielded(self) -> None:
        pages: list[Any] = [[{"id": "w1", "name": "site"}]]
        result = _run_get_rows("websites", pages)

        assert len(result.requests) == 1
        assert result.items == [[{"id": "w1", "name": "site"}]]
        assert result.saved_states == []


class TestErrorBodyLogging:
    def test_large_error_body_is_bounded_in_log(self) -> None:
        # A customer-controlled host can return a huge 4xx body; the log must carry only a bounded
        # preview plus the byte length, never interpolate the whole body (log-flooding guard).
        oversized = b"x" * (inst.ERROR_BODY_LOG_PREVIEW_BYTES + 5000)
        logger = mock.MagicMock()

        result = DRIVER.run(
            "events",
            [ScriptedResponse(status=400, body=oversized)],
            logger=logger,
        )

        assert isinstance(result.raised, requests.HTTPError)
        logged = logger.error.call_args[0][0]
        assert f"body_bytes={len(oversized)}" in logged
        # Only the preview is interpolated, not the full body.
        assert logged.count("x") == inst.ERROR_BODY_LOG_PREVIEW_BYTES


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (403, (False, 403)),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: tuple[bool, int]) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials(BASE_URL, "token", team_id=1) == expected

        assert network.requests_log[0].path == "/api/instana/version"
        assert network.requests_log[0].headers["authorization"] == "apiToken token"

    def test_transport_error_returns_none_status(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials(BASE_URL, "token", team_id=1) == (False, None)

        assert {request.path for request in network.requests_log} == {"/api/instana/version"}

    def test_blocked_host_raises(self) -> None:
        with mock.patch.object(inst, "_is_host_safe", return_value=(False, "blocked")):
            with pytest.raises(inst.InstanaHostNotAllowedError):
                validate_credentials(BASE_URL, "token", team_id=1)


class TestGetRowsHostCheck:
    def test_blocked_host_fails_the_sync(self) -> None:
        with mock.patch.object(inst, "_is_host_safe", return_value=(False, "blocked")):
            result = DRIVER.run("websites", [])

        assert isinstance(result.raised, inst.InstanaHostNotAllowedError)
        assert result.requests == []


class TestInstanaSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pk"),
        [
            ("events", ["eventId"]),
            ("applications", ["id"]),
            ("infrastructure_snapshots", ["snapshotId"]),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: list[str]) -> None:
        result = DRIVER.run(endpoint, always(ScriptedResponse(json=[])))

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
        # Instana timestamps are epoch-ms integers, so tables are unpartitioned.
        assert response.partition_mode is None
