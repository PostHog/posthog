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
    CRONITOR_ENDPOINTS,
    ENDPOINTS,
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


def _list_url(path: str, page: int, extra: str = "") -> str:
    return f"https://cronitor.io/api{path}?page={page}&pageSize={PAGE_SIZE}{extra}"


def _monitors_url(page: int) -> str:
    return _list_url("/monitors", page, "&sort=created")


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

    def test_unexpected_envelope_fails_the_sync(self, monkeypatch: Any) -> None:
        # Reading an unrecognized 200 as an empty page would let a full refresh replace the table
        # with nothing and report success.
        _patch_fetch(monkeypatch, {_monitors_url(1): {"detail": "something unexpected"}})
        with pytest.raises(cronitor.CronitorResponseShapeError):
            _collect(_FakeResumableManager(), "monitors")

    def test_sensitive_request_config_is_redacted(self, monkeypatch: Any) -> None:
        # HTTP-check monitors embed the outbound request config, which can carry credentials:
        # auth headers/cookies/body are dropped wholesale, and the check URL is reduced to scheme
        # + host/port so no userinfo, query string, or path segment can persist a token.
        monitor: dict[str, Any] = {
            "key": "check-a",
            "created": "2026-01-01T00:00:00Z",
            "request": {
                "url": "https://user:pass@example.com:8443/health?token=secret#frag",
                "method": "GET",
                "headers": {"Authorization": "Bearer super-secret"},
                "cookies": {"session": "secret-cookie"},
                "body": "api_key=secret",
            },
        }
        _patch_fetch(monkeypatch, {_monitors_url(1): {"monitors": [monitor]}})
        rows = _collect(_FakeResumableManager(), "monitors")

        assert len(rows) == 1
        assert rows[0]["request"] == {"url": "https://example.com:8443", "method": "GET"}
        # The original response dict must not be mutated in place.
        assert "headers" in monitor["request"]
        assert monitor["request"]["url"] == "https://user:pass@example.com:8443/health?token=secret#frag"

    def test_tokenized_url_path_is_not_persisted(self, monkeypatch: Any) -> None:
        # Slack incoming webhooks (and similar callback endpoints) embed the secret in a path
        # segment, so the path must be dropped, not just the query string.
        monitor: dict[str, Any] = {
            "key": "slack-check",
            "request": {"url": "https://hooks.slack.com/services/T00000/B00000/XXXXsecretXXXX"},
        }
        _patch_fetch(monkeypatch, {_monitors_url(1): {"monitors": [monitor]}})
        rows = _collect(_FakeResumableManager(), "monitors")

        assert rows[0]["request"] == {"url": "https://hooks.slack.com"}

    def test_monitor_without_request_config_is_untouched(self, monkeypatch: Any) -> None:
        # A monitor with no request config has nothing to redact and passes through unchanged.
        monitors = [{"key": "job-a", "created": "2026-01-01T00:00:00Z"}]
        _patch_fetch(monkeypatch, {_monitors_url(1): {"monitors": monitors}})
        rows = _collect(_FakeResumableManager(), "monitors")

        assert rows == monitors


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


class TestPaginatedListEndpoints:
    @pytest.mark.parametrize(
        "endpoint, path, extra, envelope_key",
        [
            ("groups", "/groups", "", "groups"),
            # Issues are ordered by start time so the page walk stays stable as incidents open.
            ("issues", "/issues", "&orderBy=started", "issues"),
            # Sites nests its rows under `data` rather than a resource-named key.
            ("sites", "/sites", "", "data"),
        ],
    )
    def test_requests_the_documented_path_and_reads_its_envelope(
        self, endpoint: str, path: str, extra: str, envelope_key: str, monkeypatch: Any
    ) -> None:
        url = _list_url(path, 1, extra)
        fetched = _patch_fetch(monkeypatch, {url: {envelope_key: [{"key": "a"}, {"key": "b"}]}})
        rows = _collect(_FakeResumableManager(), endpoint)

        assert fetched == [url]
        assert [row["key"] for row in rows] == ["a", "b"]

    def test_issues_envelope_falls_back_to_data(self, monkeypatch: Any) -> None:
        # The issues list envelope is the one Cronitor does not publish, so a `data` envelope has
        # to keep working or the table would silently sync zero rows.
        url = _list_url("/issues", 1, "&orderBy=started")
        _patch_fetch(monkeypatch, {url: {"data": [{"key": "c096dd184de20330"}]}})

        assert [row["key"] for row in _collect(_FakeResumableManager(), "issues")] == ["c096dd184de20330"]

    def test_every_schema_is_routed_to_a_transport(self, monkeypatch: Any) -> None:
        # A schema listed in the wizard but missing a transport branch only fails once a user
        # selects it, so walk every advertised endpoint against an API holding no rows.
        empty_page: dict[str, Any] = {"monitors": [], "groups": [], "issues": [], "data": []}
        _freeze_now(monkeypatch)
        monkeypatch.setattr(cronitor, "_fetch", lambda session, url, api_key, logger: empty_page)

        for endpoint in ENDPOINTS:
            assert _collect(_FakeResumableManager(), endpoint) == []


class TestSiteErrors:
    def _errors_url(self, site_key: str, page: int) -> str:
        return _list_url("/site_errors", page, f"&site={site_key}")

    def _sites_page(self, *keys: str) -> dict[str, Any]:
        return {"data": [{"key": key} for key in keys]}

    def test_fans_out_over_sites_and_tags_rows_with_site_key(self, monkeypatch: Any) -> None:
        responses = {
            _list_url("/sites", 1): self._sites_page("site-a", "site-b"),
            self._errors_url("site-a", 1): {"data": [{"key": "err-1"}]},
            self._errors_url("site-b", 1): {"data": [{"key": "err-2"}]},
        }
        _patch_fetch(monkeypatch, responses)
        manager = _FakeResumableManager()
        rows = _collect(manager, "site_errors")

        assert [(row["site_key"], row["key"]) for row in rows] == [("site-a", "err-1"), ("site-b", "err-2")]
        # The site key is injected by the fan-out, not returned by the API, so every declared
        # merge key must actually be present or the merge would key on nulls.
        primary_keys = CRONITOR_ENDPOINTS["site_errors"].primary_keys
        assert all(all(key in row for key in primary_keys) for row in rows)
        # Bookmark advanced to the next site after site-a's rows were yielded.
        assert manager.saved == [CronitorResumeConfig(site_key="site-b", page=1)]

    def test_public_report_key_is_redacted(self, monkeypatch: Any) -> None:
        # The key opens the site's performance report without a Cronitor login, so it must not
        # land in a table every project member can query.
        site: dict[str, Any] = {
            "key": "site-a",
            "name": "Main Website",
            "client_key": "ck_public",
            "public_report_key": "pr_capability",
        }
        _patch_fetch(monkeypatch, {_list_url("/sites", 1): {"data": [site]}})
        rows = _collect(_FakeResumableManager(), "sites")

        assert rows == [{"key": "site-a", "name": "Main Website", "client_key": "ck_public"}]
        # The original response dict must not be mutated in place.
        assert "public_report_key" in site

    def test_fan_out_order_does_not_follow_the_api(self, monkeypatch: Any) -> None:
        # The sites list takes no sort parameter, so a reordered list would push sites behind a
        # saved bookmark and skip them on resume.
        responses = {
            _list_url("/sites", 1): self._sites_page("site-c", "site-a", "site-b"),
            self._errors_url("site-a", 1): {"data": [{"key": "err-a"}]},
            self._errors_url("site-b", 1): {"data": [{"key": "err-b"}]},
            self._errors_url("site-c", 1): {"data": [{"key": "err-c"}]},
        }
        _patch_fetch(monkeypatch, responses)
        rows = _collect(_FakeResumableManager(), "site_errors")

        assert [row["site_key"] for row in rows] == ["site-a", "site-b", "site-c"]

    def test_paginates_within_a_site_until_short_page(self, monkeypatch: Any) -> None:
        responses = {
            _list_url("/sites", 1): self._sites_page("site-a"),
            self._errors_url("site-a", 1): {"data": [{"key": f"full-{i}"} for i in range(PAGE_SIZE)]},
            self._errors_url("site-a", 2): {"data": [{"key": "tail-0"}]},
        }
        fetched = _patch_fetch(monkeypatch, responses)
        manager = _FakeResumableManager()
        rows = _collect(manager, "site_errors")

        assert len(rows) == PAGE_SIZE + 1
        assert fetched == list(responses)
        assert manager.saved == [CronitorResumeConfig(site_key="site-a", page=2)]

    def test_resumes_from_site_and_page_bookmark(self, monkeypatch: Any) -> None:
        responses = {
            _list_url("/sites", 1): self._sites_page("site-a", "site-b"),
            self._errors_url("site-b", 3): {"data": [{"key": "err-9"}]},
        }
        fetched = _patch_fetch(monkeypatch, responses)
        rows = _collect(_FakeResumableManager(CronitorResumeConfig(site_key="site-b", page=3)), "site_errors")

        assert [(row["site_key"], row["key"]) for row in rows] == [("site-b", "err-9")]
        # site-a finished before the crash, and site-b restarts at the saved page, not page 1.
        assert self._errors_url("site-a", 1) not in fetched


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
