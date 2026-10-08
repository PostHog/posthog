import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.instana import instana as inst
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.instana import (
    InstanaResumeConfig,
    _to_epoch_ms,
    instana_source,
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

BASE_URL = "https://unit-tenant.instana.io"


def _patch_host_safe():
    return mock.patch.object(inst, "_is_host_safe", return_value=(True, None))


def _make_response(status_code: int, payload: Any = None, ok: bool | None = None) -> Any:
    """Build a streaming-response mock: `_read_capped_body` reads it via `iter_content`."""
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = ok if ok is not None else status_code < 400
    body = b"" if payload is None else json.dumps(payload).encode()
    resp.iter_content.return_value = iter([body]) if body else iter([])
    resp.text = body.decode()
    return resp


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
    can_resume: bool = False,
    resume_state: InstanaResumeConfig | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[Any], list[InstanaResumeConfig], list[str]]:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    saved: list[InstanaResumeConfig] = []
    manager.save_state.side_effect = saved.append

    fetched_urls: list[str] = []

    def fake_get(url: str, timeout: Any = None, stream: bool = False) -> Any:
        fetched_urls.append(url)
        payload = pages[min(len(fetched_urls), len(pages)) - 1]
        return _make_response(200, payload)

    with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
        mock_session.return_value.get.side_effect = fake_get
        rows = list(
            inst.get_rows(
                base_url=BASE_URL,
                api_token="token",
                endpoint=endpoint,
                team_id=1,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )
    return rows, saved, fetched_urls


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestEventRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-01-10T00:00:00Z", tick=False):
            yield

    NOW_MS = 1768003200000

    def test_incremental_run_chunks_from_watermark(self) -> None:
        watermark = self.NOW_MS - int(1.5 * EVENTS_WINDOW_CHUNK_MS)
        pages = [[{"eventId": "a", "start": watermark + 1}]]
        rows, saved, fetched = _run_get_rows(
            "events",
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert len(fetched) == 2
        first, second = _query(fetched[0]), _query(fetched[1])
        assert first["from"] == [str(watermark)]
        assert first["to"] == [str(watermark + EVENTS_WINDOW_CHUNK_MS)]
        assert second["from"] == [str(watermark + EVENTS_WINDOW_CHUNK_MS)]
        assert second["to"] == [str(self.NOW_MS)]
        # Both chunks yielded rows.
        assert len(rows) == 2
        # State saved only between chunks (after the yield), never after the final chunk.
        assert [s.events_window_from for s in saved] == [watermark + EVENTS_WINDOW_CHUNK_MS]

    def test_first_sync_reaches_back_the_default_lookback(self) -> None:
        rows, _saved, fetched = _run_get_rows("events", [[]])

        expected_from = self.NOW_MS - EVENTS_DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000
        assert _query(fetched[0])["from"] == [str(expected_from)]
        assert _query(fetched[-1])["to"] == [str(self.NOW_MS)]
        assert len(fetched) == EVENTS_DEFAULT_LOOKBACK_DAYS
        # Empty windows keep advancing without yielding.
        assert rows == []

    def test_resume_starts_at_saved_window(self) -> None:
        resume_from = self.NOW_MS - EVENTS_WINDOW_CHUNK_MS // 2
        _rows, _saved, fetched = _run_get_rows(
            "events",
            [[]],
            can_resume=True,
            resume_state=InstanaResumeConfig(events_window_from=resume_from),
        )

        assert len(fetched) == 1
        assert _query(fetched[0])["from"] == [str(resume_from)]


class TestPagedRows:
    def _page(self, count: int, page: int, total_hits: int) -> dict[str, Any]:
        return {"items": [{"id": f"p{page}-{i}"} for i in range(count)], "page": page, "totalHits": total_hits}

    def test_total_hits_terminates_a_full_final_page(self) -> None:
        pages = [self._page(PAGE_SIZE, page=1, total_hits=PAGE_SIZE)]
        _rows, saved, fetched = _run_get_rows("endpoints", pages)

        assert len(fetched) == 1
        assert saved == []

    def test_resume_starts_at_saved_page(self) -> None:
        pages = [self._page(2, page=5, total_hits=1000)]
        _rows, _saved, fetched = _run_get_rows(
            "applications", pages, can_resume=True, resume_state=InstanaResumeConfig(next_page=5)
        )

        assert _query(fetched[0])["page"] == ["5"]

    def test_pagination_limit_aborts_runaway_walk(self) -> None:
        # A self-hosted host can return a full page forever while omitting a reliable totalHits, so
        # the normal termination conditions never trip; the walk must abort past MAX_CATALOG_PAGES.
        full_page = self._page(PAGE_SIZE, page=1, total_hits=10**9)
        with mock.patch.object(inst, "MAX_CATALOG_PAGES", 3):
            with pytest.raises(inst.InstanaPaginationLimitError):
                _run_get_rows("applications", [full_page])

    def test_pagination_walk_stops_at_time_budget(self) -> None:
        # A slow host can stay under the per-page limits (and the page cap) while holding the worker,
        # so the walk must also stop on a cumulative wall-clock budget. Fetch is stubbed to isolate
        # the loop from the body-reader's own clock; monotonic advances 1s per call.
        full_page = self._page(PAGE_SIZE, page=1, total_hits=10**9)
        ticker = iter(range(0, 10_000))
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        manager.load_state.return_value = None
        with (
            mock.patch.object(inst, "MAX_CATALOG_WALK_SECONDS", 5),
            mock.patch.object(inst.time, "monotonic", lambda: next(ticker)),
            mock.patch.object(inst, "_fetch", return_value=full_page),
        ):
            with pytest.raises(inst.InstanaPaginationLimitError):
                list(
                    inst._get_paged_rows(
                        mock.MagicMock(),
                        BASE_URL,
                        inst.INSTANA_ENDPOINTS["applications"],
                        mock.MagicMock(),
                        manager,
                    )
                )


class TestOffsetRows:
    @staticmethod
    def _page(n: int, start: int = 0) -> list[dict[str, Any]]:
        return [{"testResultId": f"r{start + i}"} for i in range(n)]

    def test_walks_offsets_until_short_page(self) -> None:
        pages = [self._page(PAGE_SIZE), self._page(3, start=PAGE_SIZE)]
        rows, saved, fetched = _run_get_rows("synthetic_test_ci_cds", pages)

        assert [_query(url)["offset"] for url in fetched] == [["0"], ["1"]]
        assert all(_query(url)["limit"] == [str(PAGE_SIZE)] for url in fetched)
        assert saved == [InstanaResumeConfig(next_offset=1)]
        assert sum(len(batch) for batch in rows) == PAGE_SIZE + 3

    def test_resume_starts_at_saved_offset(self) -> None:
        _rows, _saved, fetched = _run_get_rows(
            "synthetic_test_ci_cds",
            [self._page(1)],
            can_resume=True,
            resume_state=InstanaResumeConfig(next_offset=2),
        )

        assert _query(fetched[0])["offset"] == ["2"]


def _run_metric_rows(
    endpoint: str,
    pages: list[Any],
    can_resume: bool = False,
    resume_state: InstanaResumeConfig | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[Any], list[InstanaResumeConfig], list[dict[str, Any]]]:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    saved: list[InstanaResumeConfig] = []
    manager.save_state.side_effect = saved.append

    bodies: list[dict[str, Any]] = []

    def fake_post(url: str, json: Any = None, timeout: Any = None, stream: bool = False) -> Any:
        bodies.append(json)
        return _make_response(200, pages[min(len(bodies), len(pages)) - 1])

    with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
        mock_session.return_value.post.side_effect = fake_post
        rows = list(
            inst.get_rows(
                base_url=BASE_URL,
                api_token="token",
                endpoint=endpoint,
                team_id=1,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )
    return rows, saved, bodies


class TestMetricRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-01-10T15:30:00Z", tick=False):
            yield

    # 2026-01-10T00:00:00Z: the last complete day ends here.
    TODAY_MS = 1768003200000

    @staticmethod
    def _windows(bodies: list[dict[str, Any]]) -> list[int]:
        return [body["timeFrame"]["to"] for body in bodies]

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
        rows, _saved, _bodies = _run_metric_rows(
            "service_metrics", [page], should_use_incremental_field=True, db_incremental_field_last_value=self.TODAY_MS
        )

        assert rows[0] == [
            {"serviceId": "svc1", "service": service, "timestamp": 100, "calls_sum": 7, "latency_p90": 12.5},
            {"serviceId": "svc1", "service": service, "timestamp": 200, "calls_sum": 9},
        ]

    def test_paginates_within_a_window_and_resumes_from_saved_page(self) -> None:
        full = {"items": [{"application": {"id": f"a{i}"}, "metrics": {}} for i in range(PAGE_SIZE)], "totalHits": 999}
        last = {"items": [{"application": {"id": "z"}, "metrics": {"calls.sum": [[1, 1]]}}], "totalHits": 999}
        window_from = self.TODAY_MS - METRICS_WINDOW_MS

        _rows, saved, bodies = _run_metric_rows("application_metrics", [full, last])
        assert [b["pagination"]["page"] for b in bodies[:2]] == [1, 2]
        assert InstanaResumeConfig(metrics_window_from=self.TODAY_MS - 7 * METRICS_WINDOW_MS, next_page=2) in saved

        rows, _saved, bodies = _run_metric_rows(
            "application_metrics",
            [last],
            can_resume=True,
            resume_state=InstanaResumeConfig(metrics_window_from=window_from, next_page=3),
        )
        assert len(bodies) == 1
        assert bodies[0]["pagination"]["page"] == 3
        assert bodies[0]["timeFrame"]["to"] == self.TODAY_MS
        assert rows == [[{"applicationId": "z", "application": {"id": "z"}, "timestamp": 1, "calls_sum": 1}]]


class TestFanOutRows:
    def _run(self, reports: dict[str, Any]) -> tuple[list[Any], list[str]]:
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        fetched_urls: list[str] = []

        def fake_get(url: str, timeout: Any = None, stream: bool = False) -> Any:
            fetched_urls.append(url)
            path = urlparse(url).path
            if path == "/api/settings/slo":
                return _make_response(200, {"items": [{"id": slo_id} for slo_id in reports], "page": 1, "totalHits": 2})
            report = reports[path.rsplit("/", 1)[-1]]
            if report is None:
                resp = _make_response(404, {"message": "not found"})
                resp.raise_for_status.side_effect = requests.HTTPError("404", response=resp)
                return resp
            return _make_response(200, report)

        with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = fake_get
            rows = list(
                inst.get_rows(
                    base_url=BASE_URL,
                    api_token="token",
                    endpoint="slo_reports",
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        return rows, fetched_urls

    @pytest.mark.parametrize(
        "report_body",
        [
            {"sli": 0.99, "fromTimestamp": 1},
            [{"sli": 0.99, "fromTimestamp": 1}],
        ],
    )
    def test_reports_carry_parent_id_and_deleted_parent_is_skipped(self, report_body: Any) -> None:
        rows, fetched = self._run({"SLO1": report_body, "SLO_GONE": None, "SLO2": report_body})

        assert [urlparse(url).path for url in fetched[1:]] == [
            "/api/slo/report/SLO1",
            "/api/slo/report/SLO_GONE",
            "/api/slo/report/SLO2",
        ]
        assert rows == [
            [{"sli": 0.99, "fromTimestamp": 1, "sloId": "SLO1"}],
            [{"sli": 0.99, "fromTimestamp": 1, "sloId": "SLO2"}],
        ]

    def test_child_requests_count_against_the_walk_bounds(self) -> None:
        # One parent page can hold many slow child requests; the bound must trip inside the page,
        # not only when the parent walk asks for its next page.
        with mock.patch.object(inst, "MAX_CATALOG_PAGES", 1):
            with pytest.raises(inst.InstanaPaginationLimitError):
                self._run({"SLO1": {"sli": 1}, "SLO2": {"sli": 1}})

    @time_machine.travel("2026-01-10T00:00:00Z", tick=False)
    def test_apdex_reports_request_a_trailing_window(self) -> None:
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        fetched_urls: list[str] = []

        def fake_get(url: str, timeout: Any = None, stream: bool = False) -> Any:
            fetched_urls.append(url)
            if urlparse(url).path == "/api/settings/apdex":
                return _make_response(200, [{"id": "APDEX1"}])
            return _make_response(200, [{"apdexId": "APDEX1", "apdexScore": [[1, 0.9]], "from": 1, "to": 2}])

        with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = fake_get
            rows = list(
                inst.get_rows(
                    base_url=BASE_URL,
                    api_token="token",
                    endpoint="apdex_reports",
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        report_url = fetched_urls[1]
        assert urlparse(report_url).path == "/api/apdex/report/APDEX1"
        now_ms = 1768003200000
        assert _query(report_url) == {
            "from": [str(now_ms - APDEX_REPORT_WINDOW_MS)],
            "to": [str(now_ms)],
        }
        assert rows == [[{"apdexId": "APDEX1", "apdexScore": [[1, 0.9]], "from": 1, "to": 2}]]


class TestListRows:
    def test_bare_list_body_is_yielded(self) -> None:
        pages: list[Any] = [[{"id": "w1", "name": "site"}]]
        rows, saved, fetched = _run_get_rows("websites", pages)

        assert len(fetched) == 1
        assert rows == [[{"id": "w1", "name": "site"}]]
        assert saved == []


class TestErrorBodyLogging:
    def test_large_error_body_is_bounded_in_log(self) -> None:
        # A customer-controlled host can return a huge 4xx body; the log must carry only a bounded
        # preview plus the byte length, never interpolate the whole body (log-flooding guard).
        oversized = b"x" * (inst.ERROR_BODY_LOG_PREVIEW_BYTES + 5000)
        resp = mock.MagicMock()
        resp.status_code = 400
        resp.ok = False
        resp.iter_content.return_value = iter([oversized])
        resp.raise_for_status.side_effect = requests.HTTPError("400", response=resp)

        session = mock.MagicMock()
        session.get.return_value = resp
        logger = mock.MagicMock()

        with pytest.raises(requests.HTTPError):
            inst._fetch(session, f"{BASE_URL}/api/events", logger)

        logged = logger.error.call_args[0][0]
        assert f"body_bytes={len(oversized)}" in logged
        # Only the preview is interpolated, not the full body.
        assert logged.count("x") == inst.ERROR_BODY_LOG_PREVIEW_BYTES


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (403, (False, 403)),
            (500, (False, 500)),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: tuple[bool, int]) -> None:
        response = mock.MagicMock()
        response.status_code = status_code

        with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = response
            assert validate_credentials(BASE_URL, "token", team_id=1) == expected

    def test_transport_error_returns_none_status(self) -> None:
        with _patch_host_safe(), mock.patch.object(inst, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            assert validate_credentials(BASE_URL, "token", team_id=1) == (False, None)

    def test_blocked_host_raises(self) -> None:
        with mock.patch.object(inst, "_is_host_safe", return_value=(False, "blocked")):
            with pytest.raises(inst.InstanaHostNotAllowedError):
                validate_credentials(BASE_URL, "token", team_id=1)


class TestGetRowsHostCheck:
    def test_blocked_host_fails_the_sync(self) -> None:
        with mock.patch.object(inst, "_is_host_safe", return_value=(False, "blocked")):
            with pytest.raises(inst.InstanaHostNotAllowedError):
                list(
                    inst.get_rows(
                        base_url=BASE_URL,
                        api_token="token",
                        endpoint="websites",
                        team_id=1,
                        logger=mock.MagicMock(),
                        resumable_source_manager=mock.MagicMock(),
                    )
                )


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
        response = instana_source(
            base_url=BASE_URL,
            api_token="token",
            endpoint=endpoint,
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
        # Instana timestamps are epoch-ms integers, so tables are unpartitioned.
        assert response.partition_mode is None
