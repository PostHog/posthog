import threading
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamcity import (
    TeamcitySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity import teamcity
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.source import TeamcitySource
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.teamcity import (
    TeamCityResumeConfig,
    _format_teamcity_datetime,
    _parse_teamcity_datetime,
    _resolve_next_href,
    normalize_host,
    validate_credentials,
)

TEAM_ID = 1


class TestNormalizeHost:
    @parameterized.expand(
        [
            ("bare_host", "teamcity.example.com", "https://teamcity.example.com"),
            ("trailing_slash", "https://teamcity.example.com/", "https://teamcity.example.com"),
            ("app_rest_suffix", "https://teamcity.example.com/app/rest", "https://teamcity.example.com"),
            ("context_path", "https://ci.example.com/teamcity", "https://ci.example.com/teamcity"),
            ("context_path_app_rest", "https://ci.example.com/teamcity/app/rest/", "https://ci.example.com/teamcity"),
            ("explicit_http", "http://teamcity.internal:8111", "http://teamcity.internal:8111"),
            ("whitespace", "  https://teamcity.example.com  ", "https://teamcity.example.com"),
        ]
    )
    def test_valid_hosts(self, _name: str, value: str, expected: str) -> None:
        assert normalize_host(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("userinfo_injection", "https://user:pass@evil.example.com"),
            ("query_string", "https://teamcity.example.com?redirect=evil"),
            ("fragment", "https://teamcity.example.com#frag"),
            ("bad_scheme", "ftp://teamcity.example.com"),
        ]
    )
    def test_invalid_hosts_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_host(value)


class TestResolveNextHref:
    SERVER_ROOT = "https://teamcity.example.com"

    @parameterized.expand(
        [
            ("relative_path", "/app/rest/builds?locator=count:100,start:100"),
            ("same_host_absolute", "https://teamcity.example.com/app/rest/builds?locator=count:100"),
        ]
    )
    def test_on_host_cursor_is_resolved(self, _name: str, next_href: str) -> None:
        resolved = _resolve_next_href(self.SERVER_ROOT, next_href)
        assert urlparse(resolved).netloc == "teamcity.example.com"

    @parameterized.expand(
        [
            ("absolute_metadata_host", "http://169.254.169.254/latest/meta-data/"),
            ("absolute_other_host", "https://evil.example.com/app/rest/builds"),
            ("scheme_relative", "//evil.example.com/app/rest/builds"),
            ("scheme_downgrade", "http://teamcity.example.com/app/rest/builds"),
        ]
    )
    def test_off_host_cursor_raises(self, _name: str, next_href: str) -> None:
        with pytest.raises(ValueError):
            _resolve_next_href(self.SERVER_ROOT, next_href)


class TestTimestampHandling:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "20260304T025814+0000"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "20260304T025814+0000"),
            (
                "offset_datetime_converted_to_utc",
                datetime(2026, 3, 4, 5, 58, 14, tzinfo=timezone(timedelta(hours=3))),
                "20260304T025814+0000",
            ),
            ("string_passthrough", "20260304T025814+0000", "20260304T025814+0000"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_teamcity_datetime(value) == expected

    @parameterized.expand(
        [
            ("compact_timestamp", "20260715T160948+0000", datetime(2026, 7, 15, 16, 9, 48, tzinfo=UTC)),
            ("non_timestamp_string", "not-a-date", "not-a-date"),
            ("none_passthrough", None, None),
        ]
    )
    def test_parse(self, _name: str, value: Any, expected: Any) -> None:
        assert _parse_teamcity_datetime(value) == expected


def _driver(host: str = "https://teamcity.example.com") -> SourceDriver:
    return SourceDriver(TeamcitySource(), TeamcitySourceConfig(host=host, access_token="token"))


def _pages(*bodies: dict[str, Any]) -> list[ScriptedResponse]:
    return [ScriptedResponse(json=body) for body in bodies]


def _locator_of(request: RecordedRequest) -> str:
    locator = request.param("locator")
    assert locator is not None
    return locator


class TestGetRowsTopLevel:
    def test_paginates_following_next_href_and_parses_timestamps(self) -> None:
        result = _driver().run(
            "builds",
            _pages(
                {
                    "build": [{"id": 2, "finishDate": "20260715T160948+0000"}],
                    "nextHref": "/app/rest/builds?locator=count:100,start:100",
                },
                {"build": [{"id": 1, "finishDate": "20260715T150000+0000"}]},
            ),
        )

        rows = result.rows
        assert [r["id"] for r in rows] == [2, 1]
        assert rows[0]["finishDate"] == datetime(2026, 7, 15, 16, 9, 48, tzinfo=UTC)
        assert result.requests[0].path == "/app/rest/builds"
        assert _locator_of(result.requests[0]) == "branch:(default:any),state:finished,count:100"
        # The second request follows nextHref verbatim against the server root.
        assert result.urls[1] == "https://teamcity.example.com/app/rest/builds?locator=count:100,start:100"

    def test_resumes_from_saved_next_href(self) -> None:
        result = _driver().run(
            "projects",
            _pages({"project": [{"id": "b"}]}),
            resume_state=TeamCityResumeConfig(next_href="/app/rest/projects?locator=count:100,start:100"),
        )

        assert [r["id"] for r in result.rows] == ["b"]
        assert result.urls == ["https://teamcity.example.com/app/rest/projects?locator=count:100,start:100"]

    def test_tampered_resume_cursor_off_host_raises(self) -> None:
        result = _driver().run(
            "projects",
            _pages({"project": [{"id": "b"}]}),
            resume_state=TeamCityResumeConfig(next_href="http://169.254.169.254/latest/meta-data/"),
        )

        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    def test_incremental_changes_cursor_uses_since_change(self) -> None:
        result = _driver().run(
            "changes",
            _pages({"change": []}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=42,
        )
        assert "sinceChange:(id:42)" in _locator_of(result.requests[0])

    def test_full_refresh_never_leaks_cursor(self) -> None:
        # projects has no server-side filter; a stale cursor must not reach the locator.
        result = _driver().run(
            "projects",
            _pages({"project": []}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "finishDate" not in _locator_of(result.requests[0])
        assert "sinceChange" not in _locator_of(result.requests[0])


class _FakeRaw:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, amt: int, decode_content: bool = False) -> bytes:
        chunk = self._data[self._pos : self._pos + amt]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        pass


class _BlockingRaw:
    """A raw stream that blocks on read until the response is closed, then raises.

    Mimics a hostile host that keeps a socket read blocked (staying under the byte cap and the
    idle socket timeout) until the download watchdog closes the connection.
    """

    def __init__(self) -> None:
        self._closed = threading.Event()

    def read(self, amt: int, decode_content: bool = False) -> bytes:
        if self._closed.wait(timeout=5):
            raise OSError("connection closed")
        return b""

    def close(self) -> None:
        self._closed.set()


class _FakeResponse:
    def __init__(self, status_code: int, data: bytes, raw: Any = None) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.raw = raw if raw is not None else _FakeRaw(data)
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.raw.close()

    def raise_for_status(self) -> None:
        if not self.ok:
            raise AssertionError("raise_for_status called on ok response")


class TestFetchPage:
    def _session_returning(self, response: _FakeResponse) -> Any:
        session = MagicMock()
        session.get.return_value = response
        return session

    def test_parses_body_under_cap(self) -> None:
        session = self._session_returning(_FakeResponse(200, b'{"build": [{"id": 1}]}'))
        data = teamcity._fetch_page(session, "https://teamcity.example.com/app/rest/builds", {}, MagicMock())
        assert data == {"build": [{"id": 1}]}

    def test_oversized_body_raises_without_buffering(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(teamcity, "MAX_RESPONSE_BYTES", 10)
        session = self._session_returning(_FakeResponse(200, b'{"x": "' + b"y" * 50 + b'"}'))
        with pytest.raises(ValueError):
            teamcity._fetch_page(session, "https://teamcity.example.com/app/rest/builds", {}, MagicMock())

    def test_download_deadline_closes_a_blocked_read(self, monkeypatch: Any) -> None:
        # A host that keeps a read blocked (below the byte cap and socket idle timeout) must be
        # aborted by the watchdog closing the response, surfaced as a non-retryable deadline error.
        monkeypatch.setattr(teamcity, "MAX_RESPONSE_DOWNLOAD_SECONDS", 0.05)
        response = _FakeResponse(200, b"", raw=_BlockingRaw())
        session = self._session_returning(response)
        with pytest.raises(ValueError, match="download deadline"):
            teamcity._fetch_page(session, "https://teamcity.example.com/app/rest/builds", {}, MagicMock())
        assert response.closed


class TestPaginationBounds:
    def test_repeated_cursor_aborts_walk(self) -> None:
        # A server that returns the same non-empty nextHref forever must not loop indefinitely.
        result = _driver().run(
            "projects",
            always(
                ScriptedResponse(
                    json={"project": [{"id": "a"}], "nextHref": "/app/rest/projects?locator=count:100,start:100"}
                )
            ),
        )

        # First page + one repeat of the fixed cursor, then repetition is detected and the walk stops.
        assert len(result.requests) == 2
        assert result.urls[1] == "https://teamcity.example.com/app/rest/projects?locator=count:100,start:100"
        assert len(result.rows) == 2

    def test_page_cap_truncates_endless_changing_cursor(self, monkeypatch: Any) -> None:
        # Cursors that keep changing (so repetition never trips) are bounded by the hard page cap.
        monkeypatch.setattr(teamcity, "MAX_PAGES_PER_WALK", 3)
        served: list[str] = []

        def script(request: RecordedRequest) -> ScriptedResponse:
            n = len(served)
            served.append(request.url)
            return ScriptedResponse(
                json={"project": [{"id": n}], "nextHref": f"/app/rest/projects?locator=count:100,start:{(n + 1) * 100}"}
            )

        result = _driver().run("projects", script)

        # Stops after MAX_PAGES_PER_WALK pages instead of paginating forever.
        assert len(result.requests) == 3
        assert [r["id"] for r in result.rows] == [0, 1, 2]


class TestGetRowsFanOut:
    def test_fans_out_per_build_and_injects_parent_fields(self) -> None:
        result = _driver().run(
            "test_occurrences",
            _pages(
                {
                    "build": [
                        {"id": 10, "finishDate": "20260715T160948+0000"},
                        {"id": 11, "finishDate": "20260715T170000+0000"},
                    ]
                },
                {"testOccurrence": [{"id": "build:(id:10),id:1", "status": "SUCCESS"}]},
                {"testOccurrence": [{"id": "build:(id:11),id:1", "status": "FAILURE"}]},
            ),
        )

        assert result.requests[0].path == "/app/rest/builds"
        assert _locator_of(result.requests[1]) == "build:(id:10),count:1000"
        assert _locator_of(result.requests[2]) == "build:(id:11),count:1000"
        assert [r["build_id"] for r in result.rows] == [10, 11]
        assert result.rows[0]["build_finish_date"] == datetime(2026, 7, 15, 16, 9, 48, tzinfo=UTC)

    def test_incremental_cursor_windows_the_parent_builds_walk(self) -> None:
        result = _driver().run(
            "problem_occurrences",
            _pages({"build": []}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert "finishDate:(date:20260304T025814+0000,condition:after)" in _locator_of(result.requests[0])

    def test_saves_parent_page_state_after_its_children(self) -> None:
        result = _driver().run(
            "test_occurrences",
            _pages(
                {
                    "build": [{"id": 10, "finishDate": "20260715T160948+0000"}],
                    "nextHref": "/app/rest/builds?locator=count:100,start:100",
                },
                {"testOccurrence": [{"id": "build:(id:10),id:1"}]},
                {"build": []},
            ),
        )

        assert result.saved_states == [TeamCityResumeConfig(next_href="/app/rest/builds?locator=count:100,start:100")]

    def test_resumes_from_saved_parent_page(self) -> None:
        result = _driver().run(
            "test_occurrences",
            _pages({"build": []}),
            resume_state=TeamCityResumeConfig(next_href="/app/rest/builds?locator=count:100,start:100"),
        )
        assert result.urls == ["https://teamcity.example.com/app/rest/builds?locator=count:100,start:100"]

    def test_page_cap_truncates_runaway_child_pagination_with_warning(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(teamcity, "MAX_PAGES_PER_BUILD", 2)
        logger = MagicMock()
        result = _driver().run(
            "test_occurrences",
            _pages(
                {"build": [{"id": 10, "finishDate": "20260715T160948+0000"}]},
                {
                    "testOccurrence": [{"id": "build:(id:10),id:1"}],
                    "nextHref": "/app/rest/testOccurrences?locator=build:(id:10),count:1000,start:1000",
                },
                {
                    "testOccurrence": [{"id": "build:(id:10),id:2"}],
                    "nextHref": "/app/rest/testOccurrences?locator=build:(id:10),count:1000,start:2000",
                },
                # A third child page exists but must never be fetched.
                {"testOccurrence": [{"id": "build:(id:10),id:3"}]},
            ),
            logger=logger,
        )

        assert [r["id"] for r in result.rows] == ["build:(id:10),id:1", "build:(id:10),id:2"]
        assert len(result.requests) == 3
        logger.warning.assert_called_once()


class TestTeamcitySourceResponse:
    @parameterized.expand(
        [
            ("builds", ["id"], "desc", ["finishDate"]),
            ("projects", ["id"], "desc", None),
            ("changes", ["id"], "desc", ["date"]),
            ("test_occurrences", ["id"], "desc", ["build_finish_date"]),
        ]
    )
    def test_source_response_merge_and_partition_settings(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_keys: list[str] | None
    ) -> None:
        empty: dict[str, list[Any]] = {"build": [], "project": [], "change": []}
        response = _driver().run(endpoint, always(ScriptedResponse(json=empty))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == partition_keys


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_token", 200, (True, 200)),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: tuple[bool, int]) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("https://teamcity.example.com", "token", TEAM_ID) == expected
        assert network.requests_log[0].url == "https://teamcity.example.com/app/rest/server"

    def test_transport_error_maps_to_none_status(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")
        monkeypatch.setattr(teamcity, "make_tracked_session", lambda **_: session)

        assert validate_credentials("https://teamcity.example.com", "token", TEAM_ID) == (False, None)
        session.close.assert_called_once()

    def test_malformed_host_raises_before_any_request(self) -> None:
        with scripted_network([]) as network:
            with pytest.raises(ValueError):
                validate_credentials("https://user:pass@evil.example.com", "token", TEAM_ID)
        assert network.requests_log == []

    def test_http_host_rejected_on_cloud_before_any_request(self, monkeypatch: Any) -> None:
        # On Cloud the Bearer token would cross the public internet in plaintext over http.
        monkeypatch.setattr(teamcity, "is_cloud", lambda: True)
        with scripted_network([]) as network:
            with pytest.raises(ValueError, match="https"):
                validate_credentials("http://teamcity.internal:8111", "token", TEAM_ID)
        assert network.requests_log == []

    def test_http_host_rejected_on_cloud_at_sync_time(self, monkeypatch: Any) -> None:
        # The same guard must hold at sync time, so an edited stored config can't leak the token.
        monkeypatch.setattr(teamcity, "is_cloud", lambda: True)
        result = _driver("http://teamcity.internal:8111").run("projects", [])

        assert isinstance(result.raised, ValueError)
        assert "https" in str(result.raised)
        assert result.requests == []
