import json
import threading
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube import sonarqube
from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.sonarqube import (
    SonarqubeResumeConfig,
    _extract_paging,
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
            ("whitespace", "  https://sonar.example.com  ", "https://sonar.example.com"),
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


class TestExtractPaging:
    def test_paging_object_shape(self) -> None:
        # issues/components/rules/users wrap paging in a `paging` object.
        assert _extract_paging({"paging": {"pageIndex": 2, "pageSize": 500, "total": 1200}}) == (2, 500, 1200)

    def test_top_level_shape(self) -> None:
        # /api/metrics/search returns p/ps/total at the top level instead.
        assert _extract_paging({"p": 1, "ps": 500, "total": 42}) == (1, 500, 42)


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
    def test_paginates_until_total_reached(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(sonarqube, "PAGE_SIZE", 2)
        pages = {
            f"{_BASE}/api/metrics/search?p=1&ps=2": {
                "metrics": [{"key": "a"}, {"key": "b"}],
                "p": 1,
                "ps": 2,
                "total": 3,
            },
            f"{_BASE}/api/metrics/search?p=2&ps=2": {"metrics": [{"key": "c"}], "p": 2, "ps": 2, "total": 3},
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="metrics")

        assert [r["key"] for r in rows] == ["a", "b", "c"]
        assert fetched == list(pages)

    def test_passes_required_qualifier_for_projects(self, monkeypatch: Any) -> None:
        url = f"{_BASE}/api/components/search?qualifiers=TRK&p=1&ps=500"
        pages = {url: {"components": [{"key": "proj"}], "paging": {"pageIndex": 1, "pageSize": 500, "total": 1}}}
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="projects")

        assert [r["key"] for r in rows] == ["proj"]
        assert fetched == [url]

    def test_saves_resume_state_only_while_more_pages_remain(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(sonarqube, "PAGE_SIZE", 1)
        pages = {
            f"{_BASE}/api/metrics/search?p=1&ps=1": {"metrics": [{"key": "a"}], "p": 1, "ps": 1, "total": 2},
            f"{_BASE}/api/metrics/search?p=2&ps=1": {"metrics": [{"key": "b"}], "p": 2, "ps": 1, "total": 2},
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, endpoint="metrics")

        assert manager.saved == [SonarqubeResumeConfig(next_page=2)]

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
    def test_single_window_paginates_and_stops(self, monkeypatch: Any) -> None:
        pages = {
            f"{_BASE}/api/issues/search?s=CREATION_DATE&asc=true&p=1&ps=500": {
                "issues": [{"key": "i1", "creationDate": "2024-01-01T00:00:00+0000"}],
                "paging": {"pageIndex": 1, "pageSize": 500, "total": 1},
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="issues")

        assert [r["key"] for r in rows] == ["i1"]
        assert fetched == list(pages)

    def test_incremental_adds_created_after(self, monkeypatch: Any) -> None:
        url = (
            f"{_BASE}/api/issues/search?s=CREATION_DATE&asc=true&p=1&ps=500&createdAfter=2026-03-04T02%3A58%3A14%2B0000"
        )
        pages = {
            url: {
                "issues": [{"key": "i9", "creationDate": "2026-03-05T00:00:00+0000"}],
                "paging": {"pageIndex": 1, "pageSize": 500, "total": 1},
            }
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="issues",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert fetched == [url]

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

    def close(self) -> None:
        pass


class _BlockingStream:
    """A chunk read that blocks (like a peer dripping bytes under the idle timeout) until the
    watchdog tears the socket down, then fails as a real aborted read would."""

    def __init__(self) -> None:
        self.closed = threading.Event()

    def iter_content(self, chunk_size: int = 1) -> Any:
        if not self.closed.wait(timeout=5):
            raise AssertionError("watchdog did not close the response")
        raise ConnectionError("socket closed")
        yield b""  # unreachable, but makes this a generator like requests' iter_content

    def close(self) -> None:
        self.closed.set()


class TestReadBounded:
    @pytest.mark.parametrize(
        "cap, chunks, expected",
        [
            (16, [b"aaaa", b"bbbb"], b"aaaabbbb"),
            (8, [b"aaaa", b"bbbb"], b"aaaabbbb"),  # exactly at the cap is allowed
            (0, [], b""),
        ],
    )
    def test_reads_body_within_cap(self, cap, chunks, expected, monkeypatch) -> None:
        monkeypatch.setattr(sonarqube, "MAX_RESPONSE_BYTES", cap)
        assert sonarqube._read_bounded(_FakeStream(chunks)) == expected  # type: ignore[arg-type]

    def test_raises_when_body_exceeds_cap(self, monkeypatch) -> None:
        monkeypatch.setattr(sonarqube, "MAX_RESPONSE_BYTES", 4)
        with pytest.raises(ValueError):
            sonarqube._read_bounded(_FakeStream([b"aaaa", b"b"]))  # type: ignore[arg-type]

    def test_watchdog_aborts_a_read_blocked_past_the_deadline(self, monkeypatch) -> None:
        # A read that blocks mid-chunk (a server dripping bytes under the idle timeout) is cut off
        # by the watchdog closing the socket, rather than only being noticed between chunks.
        monkeypatch.setattr(sonarqube, "MAX_TRANSFER_SECONDS", 0.05)
        stream = _BlockingStream()
        with pytest.raises(ValueError):
            sonarqube._read_bounded(stream)  # type: ignore[arg-type]
        assert stream.closed.is_set()


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
