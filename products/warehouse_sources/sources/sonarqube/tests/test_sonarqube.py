import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlparse

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sonarqube import sonarqube
from products.warehouse_sources.sources.sonarqube.sonarqube import (
    SonarqubeResumeConfig,
    _error_detail,
    _format_created_after,
    get_rows,
    normalize_base_url,
    validate_credentials,
)

_BASE = "https://sonar.example.com"


class TestNormalizeBaseUrl:
    @parameterized.expand(
        [
            ("full_https", "https://sonar.example.com", "https://sonar.example.com"),
            ("bare_host_defaults_https", "sonar.example.com", "https://sonar.example.com"),
            ("trailing_slash", "https://sonar.example.com/", "https://sonar.example.com"),
            ("strips_path", "https://sonar.example.com/sonarqube/foo", "https://sonar.example.com"),
            ("keeps_port", "https://sonar.example.com:9000", "https://sonar.example.com:9000"),
            # A self-hosted domain that only contains a cloud hostname is not the cloud product.
            ("cloud_lookalike_allowed", "https://sonarcloud.io.example.com", "https://sonarcloud.io.example.com"),
            ("whitespace", "  https://sonar.example.com  ", "https://sonar.example.com"),
            # A terminal DNS dot is dropped, so the host checked is the host requested.
            ("strips_terminal_dns_dot", "https://sonar.example.com.", "https://sonar.example.com"),
            ("strips_terminal_dns_dot_with_port", "https://sonar.example.com.:9000", "https://sonar.example.com:9000"),
        ]
    )
    def test_valid(self, _name: str, value: str, expected: str) -> None:
        assert normalize_base_url(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("whitespace_only", "   "),
            ("scheme_only", "https://"),
            ("ftp", "ftp://x"),
            # Plaintext http would put the bearer token on the wire in the clear.
            ("http_rejected", "http://sonar.internal"),
            # Cloud needs an `organization` on every list endpoint, so it can only fail mid-sync.
            ("cloud_eu_rejected", "https://sonarcloud.io"),
            ("cloud_us_rejected", "https://sonarqube.us"),
            ("cloud_bare_host_rejected", "sonarcloud.io"),
            ("cloud_subdomain_rejected", "https://api.sonarcloud.io"),
            # A terminal DNS dot reaches the same cloud host, so it must not sidestep the check.
            ("cloud_trailing_dot_rejected", "https://sonarcloud.io."),
            ("cloud_subdomain_trailing_dot_rejected", "https://api.sonarcloud.io."),
            # Stripping the dot leaves no hostname at all, which must stay a rejection.
            ("dot_only_host", "https://."),
        ]
    )
    def test_invalid_raises(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_base_url(value)


class TestFormatCreatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+0000"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+0000"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+0000"),
            ("string_passthrough", "2026-03-04T02:58:14+0000", "2026-03-04T02:58:14+0000"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_created_after(value) == expected


class TestErrorDetail:
    @parameterized.expand(
        [
            (
                "sonarqube_error_shape",
                b'{"errors":[{"msg":"The \'organization\' parameter is missing"}]}',
                "The 'organization' parameter is missing",
            ),
            ("several_errors_joined", b'{"errors":[{"msg":"first"},{"msg":"second"}]}', "first; second"),
            ("unexpected_shape_falls_back_to_body", b'{"message":"nope"}', '{"message":"nope"}'),
            ("non_json_falls_back_to_body", b"<html>gateway</html>", "<html>gateway</html>"),
            ("empty_body", b"", "no error message"),
            # A non-iterable `errors` must reach the raw-body fallback rather than raise.
            ("null_errors_falls_back_to_body", b'{"errors":null}', '{"errors":null}'),
            ("numeric_errors_falls_back_to_body", b'{"errors":1}', '{"errors":1}'),
            # The server chooses the length, and the detail reaches a Temporal activity payload.
            ("oversized_msg_capped", b'{"errors":[{"msg":"' + b"x" * 5000 + b'"}]}', "x" * 500),
            # A multi-byte body still fills the cap, so the decode slice cannot be byte-tight.
            ("oversized_multibyte_body_capped", "\U0001d11e".encode() * 600, "\U0001d11e" * 500),
        ]
    )
    def test_detail(self, _name: str, body: bytes, expected: str) -> None:
        assert _error_detail(body) == expected


class _FakeResumableManager:
    def __init__(self, state: SonarqubeResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SonarqubeResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SonarqubeResumeConfig | None:
        return self._state

    def save_state(self, data: SonarqubeResumeConfig) -> None:
        self.saved.append(data)


class _FakeBatcher:
    """Yields one batch per item so save-after-yield behavior is observable without 2000+ rows."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._rows: list[dict] = []

    def batch(self, row: dict) -> None:
        self._rows.append(row)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._rows) > 0

    def get_table(self) -> list[dict]:
        rows = self._rows
        self._rows = []
        return rows


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(sonarqube, "_fetch_page", fake_fetch)
    return fetched


def _collect(monkeypatch: Any, manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    monkeypatch.setattr(sonarqube, "Batcher", _FakeBatcher)
    rows: list[dict] = []
    for batch in get_rows(
        host=_BASE,
        token="tok",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestSimplePagination:
    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        url = f"{_BASE}/api/metrics/search?p=2&ps=500"
        pages = {url: {"metrics": [{"key": "b"}], "p": 2, "ps": 500, "total": 1000}}
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(SonarqubeResumeConfig(next_page=2)), endpoint="metrics")

        assert [r["key"] for r in rows] == ["b"]
        assert fetched == [url]

    def test_raises_at_page_cap_when_server_never_stops_paging(self, monkeypatch: Any) -> None:
        # A server that always returns a full page and claims more results would loop forever;
        # the cap turns that into a non-retryable failure after MAX_PAGES fetches.
        monkeypatch.setattr(sonarqube, "MAX_PAGES", 3)
        calls = 0

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            nonlocal calls
            calls += 1
            return {"metrics": [{"key": "x"}], "p": 1, "ps": 500, "total": 10**9}

        monkeypatch.setattr(sonarqube, "_fetch_page", fake_fetch)
        with pytest.raises(ValueError):
            _collect(monkeypatch, _FakeResumableManager(), endpoint="metrics")
        assert calls == 3


class TestWindowedIssues:
    def test_rewindows_past_the_result_cap(self, monkeypatch: Any) -> None:
        # Shrink the cap so re-windowing triggers after 2 pages instead of 20.
        monkeypatch.setattr(sonarqube, "ISSUES_MAX_PAGES", 2)
        boundary = "2024-01-02T00:00:00+0000"
        pages = {
            # Window 1: total stays above pageIndex*pageSize so the loop never "completes" — it hits
            # the page cap and must re-window on the last issue's creation date.
            f"{_BASE}/api/issues/search?s=CREATION_DATE&asc=true&p=1&ps=500": {
                "issues": [{"key": "i1", "creationDate": "2024-01-01T00:00:00+0000"}],
                "paging": {"pageIndex": 1, "pageSize": 500, "total": 9999},
            },
            f"{_BASE}/api/issues/search?s=CREATION_DATE&asc=true&p=2&ps=500": {
                "issues": [{"key": "i2", "creationDate": boundary}],
                "paging": {"pageIndex": 2, "pageSize": 500, "total": 9999},
            },
            # Window 2: createdAfter = last issue's creationDate; small total so it finishes.
            f"{_BASE}/api/issues/search?s=CREATION_DATE&asc=true&p=1&ps=500&createdAfter=2024-01-02T00%3A00%3A00%2B0000": {
                "issues": [
                    {"key": "i2", "creationDate": boundary},
                    {"key": "i3", "creationDate": "2024-01-03T00:00:00+0000"},
                ],
                "paging": {"pageIndex": 1, "pageSize": 500, "total": 2},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="issues")

        # i2 re-appears across the window boundary (createdAfter is inclusive); merge dedupes on `key`.
        assert [r["key"] for r in rows] == ["i1", "i2", "i2", "i3"]
        assert fetched == list(pages)

    def test_stops_when_window_cannot_advance(self, monkeypatch: Any) -> None:
        # >cap issues sharing one creationDate can't advance the window; stop instead of looping forever.
        monkeypatch.setattr(sonarqube, "ISSUES_MAX_PAGES", 1)
        same_date = "2024-01-01T00:00:00+0000"
        pages = {
            f"{_BASE}/api/issues/search?s=CREATION_DATE&asc=true&p=1&ps=500&createdAfter=2024-01-01T00%3A00%3A00%2B0000": {
                "issues": [{"key": "i1", "creationDate": same_date}],
                "paging": {"pageIndex": 1, "pageSize": 500, "total": 9999},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="issues",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        assert [r["key"] for r in rows] == ["i1"]
        # Only the first page is fetched — no infinite re-windowing on the same timestamp.
        assert fetched == list(pages)

    def test_raises_at_page_cap_when_server_never_stops_advancing_windows(self, monkeypatch: Any) -> None:
        # Each window is bounded, but a server that keeps advancing createdAfter with full windows
        # would spawn windows forever; the cap turns that into a non-retryable failure.
        monkeypatch.setattr(sonarqube, "MAX_PAGES", 3)
        monkeypatch.setattr(sonarqube, "ISSUES_MAX_PAGES", 1)  # re-window after every page
        calls = 0

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            nonlocal calls
            calls += 1
            return {
                "issues": [{"key": f"i{calls}", "creationDate": f"2024-01-{calls:02d}T00:00:00+0000"}],
                "paging": {"pageIndex": 1, "pageSize": 500, "total": 9999},
            }

        monkeypatch.setattr(sonarqube, "_fetch_page", fake_fetch)
        with pytest.raises(ValueError):
            _collect(monkeypatch, _FakeResumableManager(), endpoint="issues")
        assert calls == 3


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self.closed = False

    def iter_content(self, chunk_size: int = 1) -> Any:
        if self._payload is None:
            return
        yield json.dumps(self._payload).encode()

    def close(self) -> None:
        self.closed = True


class _FakeStream:
    """Yields caller-supplied byte chunks so `_read_bounded`'s cap can be exercised directly."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def iter_content(self, chunk_size: int = 1) -> Any:
        yield from self._chunks


class TestReadBounded:
    def test_raises_when_body_exceeds_cap(self, monkeypatch) -> None:
        monkeypatch.setattr(sonarqube, "MAX_RESPONSE_BYTES", 4)
        with pytest.raises(ValueError):
            sonarqube._read_bounded(_FakeStream([b"aaaa", b"b"]))  # type: ignore[arg-type]

    def test_raises_when_transfer_exceeds_deadline(self, monkeypatch) -> None:
        # Fake monotonic clock: deadline is set on the first read, jumps past it before the second chunk.
        ticks = iter([0.0, 1.0, 999.0])
        monkeypatch.setattr(sonarqube.time, "monotonic", lambda: next(ticks))
        monkeypatch.setattr(sonarqube, "MAX_TRANSFER_SECONDS", 10)
        with pytest.raises(ValueError):
            sonarqube._read_bounded(_FakeStream([b"aaaa", b"bbbb"]))  # type: ignore[arg-type]


class TestFetchPageErrors:
    def test_client_error_carries_the_servers_explanation(self) -> None:
        # SonarQube sends an empty HTTP reason phrase, so the raised message has to carry the
        # server's own words or it reads "400 Client Error:  for url: ..." and names no cause.
        session = MagicMock()
        session.get.return_value = _FakeResponse(400, {"errors": [{"msg": "The 'organization' parameter is missing"}]})

        with pytest.raises(requests.HTTPError) as error:
            sonarqube._fetch_page(session, f"{_BASE}/api/rules/search", {}, MagicMock())

        assert "400 Client Error: The 'organization' parameter is missing" in str(error.value)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, payload, expected_ok, expected_code",
        [
            (200, {"valid": True}, True, 200),
            (200, {"valid": False}, False, 200),
            (401, None, False, 401),
            (503, None, False, 503),
        ],
    )
    def test_status_mapping(self, status, payload, expected_ok, expected_code, monkeypatch) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(status, payload)
        monkeypatch.setattr(sonarqube, "make_tracked_session", lambda **kwargs: session)

        assert validate_credentials(_BASE, "tok") == (expected_ok, expected_code)

    def test_transport_error_returns_none_status(self, monkeypatch) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")
        monkeypatch.setattr(sonarqube, "make_tracked_session", lambda **kwargs: session)

        assert validate_credentials(_BASE, "tok") == (False, None)


_PROJECTS_PATH = "/api/components/search"
_METRICS_PATH = "/api/metrics/search"


class _FanoutManager(_FakeResumableManager):
    """Records saves, yields and safe points in one ordered log so staging order is observable."""

    def __init__(self, state: SonarqubeResumeConfig | None = None) -> None:
        super().__init__(state)
        self.events: list[Any] = []

    def save_state(self, data: SonarqubeResumeConfig) -> None:
        super().save_state(data)
        self.events.append(("save", data.project_key, data.metric_chunk, data.next_page))

    def safe_point(self) -> None:
        self.events.append("safe_point")


def _not_found() -> requests.HTTPError:
    response = requests.Response()
    response.status_code = 404
    return requests.HTTPError("404 Client Error: not found", response=response)


def _route(monkeypatch: Any, handlers: dict[str, Any]) -> list[tuple[str, dict[str, str]]]:
    """Answer each request from `handlers[path](params)`; return the (path, params) of every request."""
    requests_made: list[tuple[str, dict[str, str]]] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query))
        requests_made.append((parsed.path, params))
        return handlers[parsed.path](params)

    monkeypatch.setattr(sonarqube, "_fetch_page", fake_fetch)
    return requests_made


def _projects(*keys: str) -> Any:
    return lambda params: {
        "components": [{"key": key} for key in keys],
        "paging": {"pageIndex": 1, "pageSize": 500, "total": len(keys)},
    }


def _metrics(*metrics: tuple[str, str]) -> Any:
    return lambda params: {
        "metrics": [{"key": key, "type": metric_type} for key, metric_type in metrics],
        "p": 1,
        "ps": 500,
        "total": len(metrics),
    }


def _fanout_rows(monkeypatch: Any, manager: _FanoutManager, endpoint: str, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        host=_BASE,
        token="tok",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        manager.events.append(("yield", len(batch)))
        rows.extend(batch)
    return rows


class TestQualityGates:
    def test_list_is_read_in_one_unpaged_request(self, monkeypatch: Any) -> None:
        made = _route(
            monkeypatch,
            {"/api/qualitygates/list": lambda params: {"qualitygates": [{"name": "Sonar way"}, {"name": "Strict"}]}},
        )

        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="quality_gates")

        assert [r["name"] for r in rows] == ["Sonar way", "Strict"]
        assert made == [("/api/qualitygates/list", {})]

    def test_project_status_is_read_per_project_and_skips_a_deleted_project(self, monkeypatch: Any) -> None:
        def status(params: dict[str, str]) -> dict:
            if params["projectKey"] == "gone":
                raise _not_found()
            return {"projectStatus": {"status": "OK" if params["projectKey"] == "a" else "ERROR", "conditions": []}}

        made = _route(
            monkeypatch, {_PROJECTS_PATH: _projects("a", "gone", "b"), "/api/qualitygates/project_status": status}
        )

        rows = _fanout_rows(monkeypatch, _FanoutManager(), "project_quality_gate_status")

        assert rows == [
            {"projectKey": "a", "status": "OK", "conditions": []},
            {"projectKey": "b", "status": "ERROR", "conditions": []},
        ]
        assert [params for path, params in made if path != _PROJECTS_PATH] == [
            {"projectKey": "a"},
            {"projectKey": "gone"},
            {"projectKey": "b"},
        ]

    def test_project_status_raises_other_errors(self, monkeypatch: Any) -> None:
        def status(params: dict[str, str]) -> dict:
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError("403 Client Error: forbidden", response=response)

        _route(monkeypatch, {_PROJECTS_PATH: _projects("a"), "/api/qualitygates/project_status": status})

        with pytest.raises(requests.HTTPError):
            _fanout_rows(monkeypatch, _FanoutManager(), "project_quality_gate_status")


class TestHotspots:
    def test_walks_pages_per_project_and_sends_both_project_param_names(self, monkeypatch: Any) -> None:
        def hotspots(params: dict[str, str]) -> dict:
            page = int(params["p"])
            total = 2 if params["project"] == "a" else 1
            return {
                "hotspots": [{"key": f"{params['project']}-{page}"}],
                "paging": {"pageIndex": page, "pageSize": 1, "total": total},
            }

        made = _route(monkeypatch, {_PROJECTS_PATH: _projects("a", "b"), "/api/hotspots/search": hotspots})

        rows = _fanout_rows(monkeypatch, _FanoutManager(), "hotspots")

        assert [r["key"] for r in rows] == ["a-1", "a-2", "b-1"]
        assert [params for path, params in made if path == "/api/hotspots/search"] == [
            {"project": "a", "projectKey": "a", "p": "1", "ps": "500"},
            {"project": "a", "projectKey": "a", "p": "2", "ps": "500"},
            {"project": "b", "projectKey": "b", "p": "1", "ps": "500"},
        ]

    def test_stops_a_project_at_the_result_ceiling(self, monkeypatch: Any) -> None:
        # The server refuses p*ps > 10,000, so a project that claims more stops at the last page it serves.
        def hotspots(params: dict[str, str]) -> dict:
            page = int(params["p"])
            return {"hotspots": [{"key": f"h{page}"}], "paging": {"pageIndex": page, "pageSize": 500, "total": 50_000}}

        made = _route(monkeypatch, {_PROJECTS_PATH: _projects("a"), "/api/hotspots/search": hotspots})

        rows = _fanout_rows(monkeypatch, _FanoutManager(), "hotspots")

        assert len(rows) == 20
        assert sum(1 for path, _ in made if path == "/api/hotspots/search") == 20


class TestComponentMeasures:
    def test_chunks_supported_metrics_and_flattens_one_row_per_component_and_metric(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(sonarqube, "METRIC_KEYS_PER_REQUEST", 2)

        def tree(params: dict[str, str]) -> dict:
            page = int(params["p"])
            metric = params["metricKeys"].split(",")[0]
            return {
                "baseComponent": {
                    "key": "a",
                    "name": "A",
                    "qualifier": "TRK",
                    "measures": [{"metric": metric, "value": "9"}],
                },
                "components": [
                    {
                        "key": f"a:f{page}",
                        "qualifier": "FIL",
                        "path": f"f{page}",
                        "language": "py",
                        "measures": [{"metric": metric, "period": {"value": "1"}}, "not-a-measure"],
                    }
                ],
                "paging": {"pageIndex": page, "pageSize": 1, "total": 2},
            }

        made = _route(
            monkeypatch,
            {
                _PROJECTS_PATH: _projects("a"),
                _METRICS_PATH: _metrics(
                    ("ncloc", "INT"),
                    ("coverage", "PERCENT"),
                    ("dist", "DISTRIB"),
                    ("details", "DATA"),
                    ("alert_status", "LEVEL"),
                ),
                "/api/measures/component_tree": tree,
            },
        )

        rows = _fanout_rows(monkeypatch, _FanoutManager(), "component_measures")

        assert [params for path, params in made if path == "/api/measures/component_tree"] == [
            {"strategy": "all", "component": "a", "metricKeys": "ncloc,coverage", "p": "1", "ps": "500"},
            {"strategy": "all", "component": "a", "metricKeys": "ncloc,coverage", "p": "2", "ps": "500"},
            {"strategy": "all", "component": "a", "metricKeys": "alert_status", "p": "1", "ps": "500"},
            {"strategy": "all", "component": "a", "metricKeys": "alert_status", "p": "2", "ps": "500"},
        ]
        # The base component repeats on every page but is taken once per metric chunk.
        assert [(r["component"], r["metric"], r["value"], r["periodValue"]) for r in rows] == [
            ("a", "ncloc", "9", None),
            ("a:f1", "ncloc", None, "1"),
            ("a:f2", "ncloc", None, "1"),
            ("a", "alert_status", "9", None),
            ("a:f1", "alert_status", None, "1"),
            ("a:f2", "alert_status", None, "1"),
        ]
        assert rows[1] == {
            "project": "a",
            "component": "a:f1",
            "componentName": None,
            "qualifier": "FIL",
            "path": "f1",
            "language": "py",
            "metric": "ncloc",
            "value": None,
            "bestValue": None,
            "periodValue": "1",
        }

    def test_sends_no_measure_request_when_no_metric_is_supported(self, monkeypatch: Any) -> None:
        made = _route(monkeypatch, {_PROJECTS_PATH: _projects("a"), _METRICS_PATH: _metrics(("dist", "DISTRIB"))})

        assert _fanout_rows(monkeypatch, _FanoutManager(), "component_measures") == []
        assert {path for path, _ in made} == {_PROJECTS_PATH, _METRICS_PATH}


class TestMeasuresHistory:
    @parameterized.expand(
        [
            ("full_refresh", False, None, None),
            # The window starts a day early so an analysis processed after the last sync is not skipped.
            ("incremental_datetime", True, datetime(2026, 3, 4, 12, 0, tzinfo=UTC), "2026-03-03T12:00:00+0000"),
            ("incremental_date", True, date(2026, 3, 4), "2026-03-03T00:00:00+0000"),
            ("incremental_without_watermark", True, None, None),
        ]
    )
    def test_request_shaping(self, _name: str, incremental: bool, last_value: Any, expected_from: str | None) -> None:
        monkeypatch = pytest.MonkeyPatch()
        try:
            made = _route(
                monkeypatch,
                {
                    _PROJECTS_PATH: _projects("a"),
                    _METRICS_PATH: _metrics(("ncloc", "INT")),
                    "/api/measures/search_history": lambda params: {
                        "measures": [],
                        "paging": {"pageIndex": 1, "pageSize": 1000, "total": 0},
                    },
                },
            )
            _fanout_rows(
                monkeypatch,
                _FanoutManager(),
                "measures_history",
                should_use_incremental_field=incremental,
                db_incremental_field_last_value=last_value,
            )
        finally:
            monkeypatch.undo()

        expected = {"component": "a", "metrics": "ncloc", "p": "1", "ps": "1000"}
        if expected_from:
            expected["from"] = expected_from
        assert [params for path, params in made if path == "/api/measures/search_history"] == [expected]

    def test_flattens_history_points_and_drops_points_without_a_value(self, monkeypatch: Any) -> None:
        _route(
            monkeypatch,
            {
                _PROJECTS_PATH: _projects("a"),
                _METRICS_PATH: _metrics(("ncloc", "INT"), ("coverage", "PERCENT")),
                "/api/measures/search_history": lambda params: {
                    "measures": [
                        {"metric": "ncloc", "history": [{"date": "d1", "value": "10"}, {"date": "d2", "value": "12"}]},
                        {"metric": "coverage", "history": [{"date": "d1"}, {"date": "d2", "value": "80.0"}]},
                    ],
                    "paging": {"pageIndex": 1, "pageSize": 1000, "total": 2},
                },
            },
        )

        rows = _fanout_rows(monkeypatch, _FanoutManager(), "measures_history")

        assert rows == [
            {"project": "a", "metric": "ncloc", "date": "d1", "value": "10"},
            {"project": "a", "metric": "ncloc", "date": "d2", "value": "12"},
            {"project": "a", "metric": "coverage", "date": "d2", "value": "80.0"},
        ]


class TestFanoutResume:
    @staticmethod
    def _hotspot_pages(params: dict[str, str]) -> dict:
        page = int(params["p"])
        rows = [] if params["project"] == "empty" else [{"key": f"{params['project']}-{page}"}]
        return {"hotspots": rows, "paging": {"pageIndex": page, "pageSize": 1, "total": 2 if rows else 0}}

    def test_stages_the_next_position_before_each_yield_and_safe_points_empty_pages(self, monkeypatch: Any) -> None:
        _route(monkeypatch, {_PROJECTS_PATH: _projects("a", "empty", "b"), "/api/hotspots/search": self._hotspot_pages})
        manager = _FanoutManager()

        _fanout_rows(monkeypatch, manager, "hotspots")

        assert manager.events == [
            "safe_point",  # after the projects listing
            ("save", "a", 0, 2),
            ("yield", 1),
            ("save", "empty", 0, 1),
            ("yield", 1),
            ("save", "b", 0, 1),
            "safe_point",
            ("save", "b", 0, 2),
            ("yield", 1),
            ("yield", 1),
        ]

    @parameterized.expand(
        [
            ("mid_project", SonarqubeResumeConfig(project_key="b", metric_chunk=0, next_page=2), ["b-2", "c-1", "c-2"]),
            ("start_of_project", SonarqubeResumeConfig(project_key="c", metric_chunk=0, next_page=1), ["c-1", "c-2"]),
            # A project deleted since the last attempt cannot be located, so the run starts over.
            (
                "project_gone",
                SonarqubeResumeConfig(project_key="deleted", metric_chunk=0, next_page=2),
                ["a-1", "a-2", "b-1", "b-2", "c-1", "c-2"],
            ),
        ]
    )
    def test_resumes_from_saved_position(
        self, _name: str, state: SonarqubeResumeConfig, expected_keys: list[str]
    ) -> None:
        monkeypatch = pytest.MonkeyPatch()
        try:
            _route(monkeypatch, {_PROJECTS_PATH: _projects("a", "b", "c"), "/api/hotspots/search": self._hotspot_pages})
            rows = _fanout_rows(monkeypatch, _FanoutManager(state), "hotspots")
        finally:
            monkeypatch.undo()

        assert [r["key"] for r in rows] == expected_keys

    def test_resumes_at_the_saved_metric_chunk(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(sonarqube, "METRIC_KEYS_PER_REQUEST", 1)
        made = _route(
            monkeypatch,
            {
                _PROJECTS_PATH: _projects("a", "b"),
                _METRICS_PATH: _metrics(("ncloc", "INT"), ("coverage", "PERCENT")),
                "/api/measures/search_history": lambda params: {
                    "measures": [],
                    "paging": {"pageIndex": 1, "pageSize": 1000, "total": 0},
                },
            },
        )

        _fanout_rows(
            monkeypatch,
            _FanoutManager(SonarqubeResumeConfig(project_key="a", metric_chunk=1, next_page=1)),
            "measures_history",
        )

        assert [
            (params["component"], params["metrics"]) for path, params in made if path.endswith("search_history")
        ] == [
            ("a", "coverage"),
            ("b", "ncloc"),
            ("b", "coverage"),
        ]


def _unknown_url() -> requests.HTTPError:
    response = requests.Response()
    response.status_code = 404
    return requests.HTTPError(
        "404 Client Error: Unknown url : /api/project_pull_requests/list for url: https://sonar.example.com",
        response=response,
    )


class TestProjectRows:
    @parameterized.expand(
        [
            (
                "analyses_full_refresh",
                "project_analyses",
                "/api/project_analyses/search",
                "analyses",
                None,
                {"project": "a", "p": "1", "ps": "500"},
            ),
            # The window starts a day early so an analysis processed after the last sync is not skipped.
            (
                "analyses_incremental",
                "project_analyses",
                "/api/project_analyses/search",
                "analyses",
                datetime(2026, 3, 4, 12, 0, tzinfo=UTC),
                {"project": "a", "from": "2026-03-03T12:00:00+0000", "p": "1", "ps": "500"},
            ),
            ("branches_unpaged", "project_branches", "/api/project_branches/list", "branches", None, {"project": "a"}),
            (
                "pull_requests_unpaged",
                "project_pull_requests",
                "/api/project_pull_requests/list",
                "pullRequests",
                None,
                {"project": "a"},
            ),
        ]
    )
    def test_request_shaping_and_rows_carry_the_project(
        self, _name: str, endpoint: str, path: str, response_key: str, last_value: Any, expected: dict[str, str]
    ) -> None:
        monkeypatch = pytest.MonkeyPatch()
        try:
            made = _route(
                monkeypatch,
                {
                    _PROJECTS_PATH: _projects("a"),
                    # A list endpoint without paging fields is read once.
                    path: lambda params: {response_key: [{"key": "k1", "name": "n1"}]},
                },
            )
            rows = _fanout_rows(
                monkeypatch,
                _FanoutManager(),
                endpoint,
                should_use_incremental_field=last_value is not None,
                db_incremental_field_last_value=last_value,
            )
        finally:
            monkeypatch.undo()

        assert [params for request_path, params in made if request_path == path] == [expected]
        assert rows == [{"project": "a", "key": "k1", "name": "n1"}]

    def test_stops_when_the_server_does_not_serve_the_endpoint(self, monkeypatch: Any) -> None:
        def pull_requests(params: dict[str, str]) -> dict:
            raise _unknown_url()

        made = _route(
            monkeypatch,
            {_PROJECTS_PATH: _projects("a", "b", "c"), "/api/project_pull_requests/list": pull_requests},
        )

        assert _fanout_rows(monkeypatch, _FanoutManager(), "project_pull_requests") == []
        # Community Build answers the same 404 for every project, so one request is enough to stop.
        assert sum(1 for path, _ in made if path == "/api/project_pull_requests/list") == 1


class _ChangelogManager(_FanoutManager):
    def save_state(self, data: SonarqubeResumeConfig) -> None:
        self.events.append(("save", data.next_page, data.issue_key))


_ISSUES_PATH = "/api/issues/search"
_CHANGELOG_PATH = "/api/issues/changelog"


def _issue_pages(*pages: list[str]) -> Any:
    def handler(params: dict[str, str]) -> dict:
        page = int(params["p"])
        total = sum(len(keys) for keys in pages)
        return {
            "issues": [{"key": key, "project": "p"} for key in pages[page - 1]],
            "paging": {"pageIndex": page, "pageSize": len(pages[0]), "total": total},
        }

    return handler


class TestIssueChangelog:
    def test_numbers_each_issues_changes_skips_a_deleted_issue_and_stages_before_each_yield(
        self, monkeypatch: Any
    ) -> None:
        def changelog(params: dict[str, str]) -> dict:
            if params["issue"] == "gone":
                raise _not_found()
            if params["issue"] == "i1":
                return {
                    "changelog": [
                        {"creationDate": "d1", "diffs": [{"key": "issueStatus", "newValue": "ACCEPTED"}]},
                        {"creationDate": "d1", "diffs": [{"key": "assignee", "newValue": "me"}]},
                    ]
                }
            return {"changelog": []}

        made = _route(monkeypatch, {_ISSUES_PATH: _issue_pages(["i1", "gone", "i2"]), _CHANGELOG_PATH: changelog})
        manager = _ChangelogManager()

        rows = _fanout_rows(monkeypatch, manager, "issue_changelog")

        # Two changes made in the same second stay distinct rows through their position.
        assert rows == [
            {
                "issue": "i1",
                "project": "p",
                "changeIndex": 0,
                "creationDate": "d1",
                "diffs": [{"key": "issueStatus", "newValue": "ACCEPTED"}],
            },
            {
                "issue": "i1",
                "project": "p",
                "changeIndex": 1,
                "creationDate": "d1",
                "diffs": [{"key": "assignee", "newValue": "me"}],
            },
        ]
        assert [params for path, params in made if path == _CHANGELOG_PATH] == [
            {"issue": "i1"},
            {"issue": "gone"},
            {"issue": "i2"},
        ]
        assert manager.events == [
            "safe_point",  # after the issues page
            ("save", 1, "i1"),
            ("yield", 2),
            ("save", 1, "gone"),
            "safe_point",
            ("save", 1, "i2"),
            "safe_point",
        ]

    @parameterized.expand(
        [
            ("after_an_issue", SonarqubeResumeConfig(next_page=2, issue_key="i3"), ["i4"]),
            ("after_the_last_issue_of_a_page", SonarqubeResumeConfig(next_page=1, issue_key="i2"), ["i3", "i4"]),
            # An issue deleted since the last attempt cannot be located, so its page is read again.
            ("issue_gone", SonarqubeResumeConfig(next_page=2, issue_key="deleted"), ["i3", "i4"]),
        ]
    )
    def test_resumes_after_the_saved_issue(
        self, _name: str, state: SonarqubeResumeConfig, expected_issues: list[str]
    ) -> None:
        monkeypatch = pytest.MonkeyPatch()
        try:
            made = _route(
                monkeypatch,
                {
                    _ISSUES_PATH: _issue_pages(["i1", "i2"], ["i3", "i4"]),
                    _CHANGELOG_PATH: lambda params: {"changelog": []},
                },
            )
            _fanout_rows(monkeypatch, _ChangelogManager(state), "issue_changelog")
        finally:
            monkeypatch.undo()

        assert [params["issue"] for path, params in made if path == _CHANGELOG_PATH] == expected_issues
