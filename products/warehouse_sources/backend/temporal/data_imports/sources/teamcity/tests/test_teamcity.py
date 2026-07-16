from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity import teamcity
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.settings import TEAMCITY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.teamcity import (
    TeamCityResumeConfig,
    _format_teamcity_datetime,
    _incremental_locator_dimensions,
    _parse_teamcity_datetime,
    _resolve_next_href,
    get_rows,
    normalize_host,
    teamcity_source,
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


class TestIncrementalLocatorDimensions:
    def test_builds_use_finish_date_condition_after(self) -> None:
        dims = _incremental_locator_dimensions(
            TEAMCITY_ENDPOINTS["builds"], datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        )
        assert dims == {"finishDate": "(date:20260304T025814+0000,condition:after)"}

    def test_changes_use_since_change_id(self) -> None:
        dims = _incremental_locator_dimensions(TEAMCITY_ENDPOINTS["changes"], 42)
        assert dims == {"sinceChange": "(id:42)"}

    def test_no_cursor_means_no_filter(self) -> None:
        assert _incremental_locator_dimensions(TEAMCITY_ENDPOINTS["builds"], None) == {}


class _FakeResumableManager:
    def __init__(self, state: TeamCityResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TeamCityResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TeamCityResumeConfig | None:
        return self._state

    def save_state(self, data: TeamCityResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, responses: list[dict[str, Any]]) -> list[str]:
    """Return page payloads in call order, recording each requested URL."""
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict[str, Any]:
        fetched.append(url)
        return responses[len(fetched) - 1]

    monkeypatch.setattr(teamcity, "_fetch_page", fake_fetch)
    return fetched


def _locator_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["locator"][0]


def _collect(manager: _FakeResumableManager, **kwargs: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in get_rows(
        host="https://teamcity.example.com",
        access_token="token",
        team_id=TEAM_ID,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestGetRowsTopLevel:
    def test_paginates_following_next_href_and_parses_timestamps(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(
            monkeypatch,
            [
                {
                    "build": [{"id": 2, "finishDate": "20260715T160948+0000"}],
                    "nextHref": "/app/rest/builds?locator=count:100,start:100",
                },
                {"build": [{"id": 1, "finishDate": "20260715T150000+0000"}]},
            ],
        )
        rows = _collect(_FakeResumableManager(), endpoint="builds")

        assert [r["id"] for r in rows] == [2, 1]
        assert rows[0]["finishDate"] == datetime(2026, 7, 15, 16, 9, 48, tzinfo=UTC)
        first = urlparse(fetched[0])
        assert first.path == "/app/rest/builds"
        assert _locator_of(fetched[0]) == "branch:(default:any),state:finished,count:100"
        # The second request follows nextHref verbatim against the server root.
        assert fetched[1] == "https://teamcity.example.com/app/rest/builds?locator=count:100,start:100"

    def test_saves_resume_state_only_while_more_pages_remain(self, monkeypatch: Any) -> None:
        _patch_fetch(
            monkeypatch,
            [
                {"project": [{"id": "a"}], "nextHref": "/app/rest/projects?locator=count:100,start:100"},
                {"project": [{"id": "b"}]},
            ],
        )
        manager = _FakeResumableManager()
        _collect(manager, endpoint="projects")

        assert manager.saved == [TeamCityResumeConfig(next_href="/app/rest/projects?locator=count:100,start:100")]

    def test_resumes_from_saved_next_href(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, [{"project": [{"id": "b"}]}])
        rows = _collect(
            _FakeResumableManager(TeamCityResumeConfig(next_href="/app/rest/projects?locator=count:100,start:100")),
            endpoint="projects",
        )

        assert [r["id"] for r in rows] == ["b"]
        assert fetched == ["https://teamcity.example.com/app/rest/projects?locator=count:100,start:100"]

    def test_tampered_resume_cursor_off_host_raises(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, [{"project": [{"id": "b"}]}])
        with pytest.raises(ValueError):
            _collect(
                _FakeResumableManager(TeamCityResumeConfig(next_href="http://169.254.169.254/latest/meta-data/")),
                endpoint="projects",
            )
        assert fetched == []

    def test_incremental_builds_cursor_windows_the_locator(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, [{"build": []}])
        _collect(
            _FakeResumableManager(),
            endpoint="builds",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert "finishDate:(date:20260304T025814+0000,condition:after)" in _locator_of(fetched[0])

    def test_incremental_changes_cursor_uses_since_change(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, [{"change": []}])
        _collect(
            _FakeResumableManager(),
            endpoint="changes",
            should_use_incremental_field=True,
            db_incremental_field_last_value=42,
        )
        assert "sinceChange:(id:42)" in _locator_of(fetched[0])

    def test_full_refresh_never_leaks_cursor(self, monkeypatch: Any) -> None:
        # projects has no server-side filter; a stale cursor must not reach the locator.
        fetched = _patch_fetch(monkeypatch, [{"project": []}])
        _collect(
            _FakeResumableManager(),
            endpoint="projects",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "finishDate" not in _locator_of(fetched[0])
        assert "sinceChange" not in _locator_of(fetched[0])


class TestPaginationBounds:
    def test_repeated_cursor_aborts_walk(self, monkeypatch: Any) -> None:
        # A server that returns the same non-empty nextHref forever must not loop indefinitely.
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict[str, Any]:
            fetched.append(url)
            return {"project": [{"id": "a"}], "nextHref": "/app/rest/projects?locator=count:100,start:100"}

        monkeypatch.setattr(teamcity, "_fetch_page", fake_fetch)
        rows = _collect(_FakeResumableManager(), endpoint="projects")

        # First page + one repeat of the fixed cursor, then repetition is detected and the walk stops.
        assert fetched == [
            mock.ANY,
            "https://teamcity.example.com/app/rest/projects?locator=count:100,start:100",
        ]
        assert len(rows) == 2

    def test_page_cap_truncates_endless_changing_cursor(self, monkeypatch: Any) -> None:
        # Cursors that keep changing (so repetition never trips) are bounded by the hard page cap.
        monkeypatch.setattr(teamcity, "MAX_PAGES_PER_WALK", 3)
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict[str, Any]:
            n = len(fetched)
            fetched.append(url)
            return {"project": [{"id": n}], "nextHref": f"/app/rest/projects?locator=count:100,start:{(n + 1) * 100}"}

        monkeypatch.setattr(teamcity, "_fetch_page", fake_fetch)
        rows = _collect(_FakeResumableManager(), endpoint="projects")

        # Stops after MAX_PAGES_PER_WALK pages instead of paginating forever.
        assert len(fetched) == 3
        assert [r["id"] for r in rows] == [0, 1, 2]


class TestGetRowsFanOut:
    def test_fans_out_per_build_and_injects_parent_fields(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(
            monkeypatch,
            [
                {
                    "build": [
                        {"id": 10, "finishDate": "20260715T160948+0000"},
                        {"id": 11, "finishDate": "20260715T170000+0000"},
                    ]
                },
                {"testOccurrence": [{"id": "build:(id:10),id:1", "status": "SUCCESS"}]},
                {"testOccurrence": [{"id": "build:(id:11),id:1", "status": "FAILURE"}]},
            ],
        )
        rows = _collect(_FakeResumableManager(), endpoint="test_occurrences")

        parent = urlparse(fetched[0])
        assert parent.path == "/app/rest/builds"
        assert _locator_of(fetched[1]) == "build:(id:10),count:1000"
        assert _locator_of(fetched[2]) == "build:(id:11),count:1000"
        assert [r["build_id"] for r in rows] == [10, 11]
        assert rows[0]["build_finish_date"] == datetime(2026, 7, 15, 16, 9, 48, tzinfo=UTC)

    def test_incremental_cursor_windows_the_parent_builds_walk(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, [{"build": []}])
        _collect(
            _FakeResumableManager(),
            endpoint="problem_occurrences",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert "finishDate:(date:20260304T025814+0000,condition:after)" in _locator_of(fetched[0])

    def test_saves_parent_page_state_after_its_children(self, monkeypatch: Any) -> None:
        _patch_fetch(
            monkeypatch,
            [
                {
                    "build": [{"id": 10, "finishDate": "20260715T160948+0000"}],
                    "nextHref": "/app/rest/builds?locator=count:100,start:100",
                },
                {"testOccurrence": [{"id": "build:(id:10),id:1"}]},
                {"build": []},
            ],
        )
        manager = _FakeResumableManager()
        _collect(manager, endpoint="test_occurrences")

        assert manager.saved == [TeamCityResumeConfig(next_href="/app/rest/builds?locator=count:100,start:100")]

    def test_resumes_from_saved_parent_page(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, [{"build": []}])
        _collect(
            _FakeResumableManager(TeamCityResumeConfig(next_href="/app/rest/builds?locator=count:100,start:100")),
            endpoint="test_occurrences",
        )
        assert fetched == ["https://teamcity.example.com/app/rest/builds?locator=count:100,start:100"]

    def test_page_cap_truncates_runaway_child_pagination_with_warning(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(teamcity, "MAX_PAGES_PER_BUILD", 2)
        _patch_fetch(
            monkeypatch,
            [
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
            ],
        )
        logger = MagicMock()
        rows: list[dict[str, Any]] = []
        for batch in get_rows(
            host="https://teamcity.example.com",
            access_token="token",
            endpoint="test_occurrences",
            team_id=TEAM_ID,
            logger=logger,
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        ):
            rows.extend(batch)

        assert [r["id"] for r in rows] == ["build:(id:10),id:1", "build:(id:10),id:2"]
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
        response = teamcity_source(
            host="https://teamcity.example.com",
            access_token="token",
            endpoint=endpoint,
            team_id=TEAM_ID,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == partition_keys


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_token", 200, (True, 200)),
            ("invalid_token", 401, (False, 401)),
            ("missing_permission", 403, (False, 403)),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: tuple[bool, int]) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with mock.patch.object(teamcity, "make_tracked_session", return_value=session):
            assert validate_credentials("https://teamcity.example.com", "token", TEAM_ID) == expected
        assert session.get.call_args.args[0] == "https://teamcity.example.com/app/rest/server"

    def test_transport_error_maps_to_none_status(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")
        monkeypatch.setattr(teamcity, "make_tracked_session", lambda: session)

        assert validate_credentials("https://teamcity.example.com", "token", TEAM_ID) == (False, None)

    def test_malformed_host_raises_before_any_request(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(teamcity, "make_tracked_session", MagicMock())
        with pytest.raises(ValueError):
            validate_credentials("https://user:pass@evil.example.com", "token", TEAM_ID)

    def test_http_host_rejected_on_cloud_before_any_request(self, monkeypatch: Any) -> None:
        # On Cloud the Bearer token would cross the public internet in plaintext over http.
        monkeypatch.setattr(teamcity, "is_cloud", lambda: True)
        monkeypatch.setattr(teamcity, "make_tracked_session", MagicMock())
        with pytest.raises(ValueError, match="https"):
            validate_credentials("http://teamcity.internal:8111", "token", TEAM_ID)

    def test_http_host_rejected_on_cloud_at_sync_time(self, monkeypatch: Any) -> None:
        # The same guard must hold at sync time, so an edited stored config can't leak the token.
        monkeypatch.setattr(teamcity, "is_cloud", lambda: True)
        monkeypatch.setattr(teamcity, "make_tracked_session", MagicMock())
        with pytest.raises(ValueError, match="https"):
            next(
                iter(
                    get_rows(
                        host="http://teamcity.internal:8111",
                        access_token="token",
                        endpoint="projects",
                        team_id=TEAM_ID,
                        logger=MagicMock(),
                        resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                    )
                )
            )
