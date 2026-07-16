from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor import cronitor
from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.cronitor import (
    CronitorResumeConfig,
    _coerce_epoch,
    _flatten_metrics_response,
    cronitor_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.settings import (
    METRICS_MIN_WINDOW_SECONDS,
    PAGE_SIZE,
)

NOW = 1_750_000_000


class _FakeResumableManager:
    def __init__(self, state: CronitorResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CronitorResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CronitorResumeConfig | None:
        return self._state

    def save_state(self, data: CronitorResumeConfig) -> None:
        self.saved.append(data)


def _http_404() -> requests.HTTPError:
    response = MagicMock()
    response.status_code = 404
    return requests.HTTPError(response=response)


def _patch_fetch(monkeypatch: Any, responses: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, api_key: str, logger: Any) -> Any:
        fetched.append(url)
        result = responses[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cronitor, "_fetch", fake_fetch)
    return fetched


def _freeze_now(monkeypatch: Any) -> None:
    monkeypatch.setattr(cronitor, "time", SimpleNamespace(time=lambda: NOW))


def _collect(manager: _FakeResumableManager, endpoint: str, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        api_key="key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


def _monitors_url(page: int) -> str:
    return f"https://cronitor.io/api/monitors?page={page}&pageSize={PAGE_SIZE}&sort=created"


def _monitors_page(count: int, prefix: str = "job") -> dict[str, Any]:
    return {"monitors": [{"key": f"{prefix}-{i}", "created": "2026-01-01T00:00:00Z"} for i in range(count)]}


class TestCoerceEpoch:
    @parameterized.expand(
        [
            ("int", 1712000000, 1712000000),
            ("float", 1712000000.5, 1712000000),
            ("numeric_string", "1712000000", 1712000000),
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094),
            ("naive_datetime_is_utc", datetime(2026, 3, 4, 2, 58, 14), 1772593094),
            ("date_value", date(2026, 3, 4), 1772582400),
            ("iso_string", "2026-03-04T02:58:14Z", 1772593094),
            ("none", None, None),
            ("bool_is_not_a_cursor", True, None),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_coerce(self, _name: str, value: Any, expected: int | None) -> None:
        assert _coerce_epoch(value) == expected


class TestMonitors:
    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        responses = {
            _monitors_url(1): _monitors_page(PAGE_SIZE),
            _monitors_url(2): _monitors_page(3, prefix="tail"),
        }
        fetched = _patch_fetch(monkeypatch, responses)
        manager = _FakeResumableManager()
        rows = _collect(manager, "monitors")

        assert len(rows) == PAGE_SIZE + 3
        # A short page signals the end — no extra empty-page request.
        assert fetched == list(responses)
        # State is saved only while more pages remain, and only after the page was yielded.
        assert manager.saved == [CronitorResumeConfig(page=2)]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        responses = {_monitors_url(3): _monitors_page(1)}
        fetched = _patch_fetch(monkeypatch, responses)
        rows = _collect(_FakeResumableManager(CronitorResumeConfig(page=3)), "monitors")

        assert len(rows) == 1
        assert fetched == [_monitors_url(3)]

    def test_unexpected_envelope_yields_nothing(self, monkeypatch: Any) -> None:
        _patch_fetch(monkeypatch, {_monitors_url(1): {"detail": "something unexpected"}})
        assert _collect(_FakeResumableManager(), "monitors") == []

    def test_sensitive_request_config_is_redacted(self, monkeypatch: Any) -> None:
        # HTTP-check monitors embed the outbound request config, which can carry credentials.
        # Those must never reach the warehouse table, but harmless request config stays.
        monitor = {
            "key": "check-a",
            "created": "2026-01-01T00:00:00Z",
            "request": {
                "url": "https://example.com/health",
                "method": "GET",
                "headers": {"Authorization": "Bearer super-secret"},
                "cookies": {"session": "secret-cookie"},
                "body": "api_key=secret",
            },
        }
        _patch_fetch(monkeypatch, {_monitors_url(1): {"monitors": [monitor]}})
        rows = _collect(_FakeResumableManager(), "monitors")

        assert len(rows) == 1
        assert rows[0]["request"] == {"url": "https://example.com/health", "method": "GET"}
        # The original response dict must not be mutated in place.
        assert "headers" in monitor["request"]


class TestInvocations:
    def _detail_url(self, key: str) -> str:
        return f"https://cronitor.io/api/monitors/{key}?withInvocations=true"

    def test_fans_out_and_tags_rows_with_monitor_key(self, monkeypatch: Any) -> None:
        responses = {
            _monitors_url(1): {"monitors": [{"key": "job-a"}, {"key": "job-b"}]},
            self._detail_url("job-a"): {
                "key": "job-a",
                "latest_invocations": [
                    {"series": "s1", "started_at": 1712000000.1, "ended_at": 1712000060.2, "duration": 60100},
                    # A run missing `series` must still get a non-null merge key.
                    {"started_at": 1712003600.0},
                ],
            },
            self._detail_url("job-b"): {"key": "job-b", "latest_invocations": []},
        }
        _patch_fetch(monkeypatch, responses)
        manager = _FakeResumableManager()
        rows = _collect(manager, "invocations")

        assert [(r["monitor_key"], r["series"]) for r in rows] == [("job-a", "s1"), ("job-a", "")]
        # Bookmark advanced to the next monitor after job-a's rows were yielded.
        assert manager.saved == [CronitorResumeConfig(monitor_key="job-b")]

    def test_deleted_monitor_is_skipped_and_sync_continues(self, monkeypatch: Any) -> None:
        responses = {
            _monitors_url(1): {"monitors": [{"key": "gone"}, {"key": "job-b"}]},
            self._detail_url("gone"): _http_404(),
            self._detail_url("job-b"): {
                "key": "job-b",
                "latest_invocations": [{"series": "s2", "started_at": 1712000000}],
            },
        }
        _patch_fetch(monkeypatch, responses)
        rows = _collect(_FakeResumableManager(), "invocations")

        assert [r["monitor_key"] for r in rows] == ["job-b"]

    def test_resumes_from_monitor_key_bookmark(self, monkeypatch: Any) -> None:
        responses = {
            _monitors_url(1): {"monitors": [{"key": "job-a"}, {"key": "job-b"}, {"key": "job-c"}]},
            self._detail_url("job-b"): {"key": "job-b", "latest_invocations": [{"series": "s2", "started_at": 1}]},
            self._detail_url("job-c"): {"key": "job-c", "latest_invocations": [{"series": "s3", "started_at": 2}]},
        }
        fetched = _patch_fetch(monkeypatch, responses)
        rows = _collect(_FakeResumableManager(CronitorResumeConfig(monitor_key="job-b")), "invocations")

        # job-a was already processed before the crash; only job-b onwards is re-fetched.
        assert [r["monitor_key"] for r in rows] == ["job-b", "job-c"]
        assert self._detail_url("job-a") not in fetched


class TestFlattenMetricsResponse:
    def test_flattens_and_coerces_stamp_to_int(self) -> None:
        data = {
            "monitors": {
                "job-a": {
                    "env:production": [
                        {"stamp": 1712000000.0, "duration_p50": 1250, "success_rate": 98.5, "run_count": 24},
                        {"stamp": 1712003600, "run_count": 0},
                    ],
                    "env:staging": [{"stamp": 1712000000, "run_count": 1}],
                },
            }
        }

        rows = _flatten_metrics_response(data)

        assert [(r["monitor_key"], r["dimension"], r["stamp"]) for r in rows] == [
            ("job-a", "env:production", 1712000000),
            ("job-a", "env:production", 1712003600),
            ("job-a", "env:staging", 1712000000),
        ]
        assert all(isinstance(r["stamp"], int) for r in rows)
        assert rows[0]["duration_p50"] == 1250

    @parameterized.expand(
        [
            ("empty", {}),
            ("null_monitors", {"monitors": None}),
            ("point_without_stamp", {"monitors": {"job-a": {"env:production": [{"run_count": 1}]}}}),
        ]
    )
    def test_malformed_responses_yield_no_rows(self, _name: str, data: Any) -> None:
        assert _flatten_metrics_response(data) == []


class TestMetrics:
    def _run(self, monkeypatch: Any, manager: _FakeResumableManager, **kwargs: Any) -> tuple[list[dict], list[str]]:
        _freeze_now(monkeypatch)
        monkeypatch.setattr(cronitor, "_list_monitor_keys", lambda session, api_key, logger: self.monitor_keys)
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, api_key: str, logger: Any) -> Any:
            fetched.append(url)
            return {"monitors": {}}

        monkeypatch.setattr(cronitor, "_fetch", fake_fetch)
        rows = _collect(manager, "metrics", **kwargs)
        return rows, fetched

    def setup_method(self) -> None:
        self.monitor_keys = ["job-a", "job-b"]

    def test_incremental_sync_requests_window_from_watermark(self, monkeypatch: Any) -> None:
        watermark = NOW - 3 * 3600
        _, fetched = self._run(
            monkeypatch,
            _FakeResumableManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert len(fetched) == 1
        params = parse_qs(urlparse(fetched[0]).query)
        assert params["monitor"] == ["job-a", "job-b"]
        assert params["field"] == ["duration_p50", "duration_p90", "success_rate", "run_count"]
        assert params["start"] == [str(watermark)]
        assert params["end"] == [str(NOW)]

    def test_sub_hour_window_is_widened_to_api_minimum(self, monkeypatch: Any) -> None:
        # The API rejects spans under an hour; the re-pulled overlap is deduped on the primary key.
        _, fetched = self._run(
            monkeypatch,
            _FakeResumableManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=NOW - 60,
        )

        params = parse_qs(urlparse(fetched[0]).query)
        assert params["start"] == [str(NOW - METRICS_MIN_WINDOW_SECONDS)]
        assert params["end"] == [str(NOW)]

    def test_backfill_walks_windows_and_checkpoints_after_each(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(cronitor, "METRICS_WINDOW_SECONDS", 3600)
        manager = _FakeResumableManager()
        _, fetched = self._run(
            monkeypatch,
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=NOW - 3 * 3600,
        )

        starts = [parse_qs(urlparse(url).query)["start"][0] for url in fetched]
        assert starts == [str(NOW - 3 * 3600), str(NOW - 2 * 3600), str(NOW - 3600)]
        # A checkpoint lands after each completed window except the last, so a crash resumes
        # mid-backfill instead of restarting from the watermark.
        assert manager.saved == [
            CronitorResumeConfig(window_start=NOW - 2 * 3600),
            CronitorResumeConfig(window_start=NOW - 3600),
        ]

    def test_resumes_from_saved_window_start(self, monkeypatch: Any) -> None:
        _, fetched = self._run(
            monkeypatch,
            _FakeResumableManager(CronitorResumeConfig(window_start=NOW - 2 * 3600)),
            should_use_incremental_field=True,
            db_incremental_field_last_value=NOW - 300 * 24 * 3600,
        )

        # The saved window wins over the (older) watermark.
        assert parse_qs(urlparse(fetched[0]).query)["start"] == [str(NOW - 2 * 3600)]

    def test_full_refresh_starts_at_max_lookback(self, monkeypatch: Any) -> None:
        _, fetched = self._run(monkeypatch, _FakeResumableManager(), should_use_incremental_field=False)

        first_start = int(parse_qs(urlparse(fetched[0]).query)["start"][0])
        assert first_start == NOW - 365 * 24 * 3600

    def test_monitors_are_batched_per_request_cap(self, monkeypatch: Any) -> None:
        self.monitor_keys = [f"job-{i}" for i in range(60)]
        _, fetched = self._run(
            monkeypatch,
            _FakeResumableManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=NOW - 2 * 3600,
        )

        monitor_counts = [len(parse_qs(urlparse(url).query)["monitor"]) for url in fetched]
        assert monitor_counts == [50, 10]

    def test_empty_window_404_is_skipped(self, monkeypatch: Any) -> None:
        _freeze_now(monkeypatch)
        monkeypatch.setattr(cronitor, "_list_monitor_keys", lambda session, api_key, logger: ["job-a"])

        def fake_fetch(session: Any, url: str, api_key: str, logger: Any) -> Any:
            raise _http_404()

        monkeypatch.setattr(cronitor, "_fetch", fake_fetch)
        rows = _collect(
            _FakeResumableManager(),
            "metrics",
            should_use_incremental_field=True,
            db_incremental_field_last_value=NOW - 2 * 3600,
        )

        assert rows == []


class TestSourceResponse:
    @parameterized.expand(
        [
            ("monitors", ["key"], "asc"),
            ("invocations", ["monitor_key", "series", "started_at"], "asc"),
            # Metrics rows aren't globally stamp-ascending (batched per monitor group per window),
            # so desc defers the watermark to job end.
            ("metrics", ["monitor_key", "dimension", "stamp"], "desc"),
        ]
    )
    def test_primary_keys_and_sort_mode(self, endpoint: str, primary_keys: list[str], sort_mode: str) -> None:
        response = cronitor_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(KeyError):
            cronitor_source(api_key="key", endpoint="nope", logger=MagicMock(), resumable_source_manager=MagicMock())
