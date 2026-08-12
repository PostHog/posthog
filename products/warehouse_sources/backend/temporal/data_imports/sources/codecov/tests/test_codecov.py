from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codecov import codecov
from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.codecov import (
    CodecovResumeConfig,
    _ensure_codecov_url,
    _owner_base_url,
    _should_stop_desc,
    get_rows,
    parse_repositories,
    validate_credentials,
)

_BASE = "https://api.codecov.io/api/v2/github/acme"


class _FakeResumableManager:
    def __init__(self, state: CodecovResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CodecovResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CodecovResumeConfig | None:
        return self._state

    def save_state(self, data: CodecovResumeConfig) -> None:
        self.saved.append(data)


def _http_error(status_code: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status_code
    return requests.HTTPError(response=response)


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        fetched.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(codecov, "_fetch_page", fake_fetch)
    return fetched


def _collect(manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        api_token="token",
        service="github",
        owner_username="acme",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


def _page(results: list[dict], next_url: str | None = None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


_ACTIVE_REPOS_URL = f"{_BASE}/repos?active=true&page_size=500"


class TestParseRepositories:
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty", "", []),
            ("single", "repo-one", ["repo-one"]),
            ("comma_separated_with_spaces", " repo-one , repo-two ", ["repo-one", "repo-two"]),
            ("trailing_commas", "repo-one,,", ["repo-one"]),
        ]
    )
    def test_parse(self, _name: str, value: str | None, expected: list[str]) -> None:
        assert parse_repositories(value) == expected


class TestOwnerBaseUrl:
    @parameterized.expand(
        [
            ("plain", "acme", "https://api.codecov.io/api/v2/github/acme"),
            # Path metacharacters must be encoded so a crafted owner can't retarget the
            # request path the bearer token is sent to.
            ("slash", "acme/../evil", "https://api.codecov.io/api/v2/github/acme%2F..%2Fevil"),
            ("query", "acme?x=1", "https://api.codecov.io/api/v2/github/acme%3Fx%3D1"),
        ]
    )
    def test_owner_is_percent_encoded(self, _name: str, owner: str, expected: str) -> None:
        assert _owner_base_url("github", owner) == expected


class TestEnsureCodecovUrl:
    @parameterized.expand(
        [
            ("http_upgraded", "http://api.codecov.io/api/v2/github/acme/repos?page=2"),
            ("https_unchanged", "https://api.codecov.io/api/v2/github/acme/repos?page=2"),
        ]
    )
    def test_valid_urls_normalize_to_https(self, _name: str, url: str) -> None:
        assert _ensure_codecov_url(url) == "https://api.codecov.io/api/v2/github/acme/repos?page=2"

    @parameterized.expand(
        [
            # A pagination link or poisoned resume state pointing anywhere but the Codecov API
            # origin would receive the bearer token — refuse it.
            ("foreign_host", "https://evil.example.com/api/v2/github/acme/repos"),
            ("userinfo_trick", "https://api.codecov.io@evil.example.com/api/v2/repos"),
            ("host_suffix", "https://api.codecov.io.evil.example.com/api/v2/repos"),
            ("path_prefix_escape", "https://api.codecov.io/api/v2evil"),
        ]
    )
    def test_non_codecov_urls_are_refused(self, _name: str, url: str) -> None:
        with pytest.raises(ValueError):
            _ensure_codecov_url(url)


class TestShouldStopDesc:
    _CUTOFF = datetime(2026, 7, 5, tzinfo=UTC)

    @parameterized.expand(
        [
            ("no_cutoff", [{"timestamp": "2026-07-01T00:00:00Z"}], "timestamp", None, False),
            ("all_newer", [{"timestamp": "2026-07-09T00:00:00Z"}], "timestamp", _CUTOFF, False),
            (
                "one_older",
                [{"timestamp": "2026-07-09T00:00:00Z"}, {"timestamp": "2026-07-01T00:00:00Z"}],
                "timestamp",
                _CUTOFF,
                True,
            ),
            ("missing_field", [{"other": "x"}], "timestamp", _CUTOFF, False),
            ("no_field", [{"timestamp": "2026-07-01T00:00:00Z"}], None, _CUTOFF, False),
        ]
    )
    def test_stop(self, _name: str, items: list[dict], field: str | None, cutoff: Any, expected: bool) -> None:
        assert _should_stop_desc(items, field, cutoff) is expected


class TestTopLevelRows:
    def test_repos_paginates_and_upgrades_next_to_https(self, monkeypatch: Any) -> None:
        pages = {
            f"{_BASE}/repos?page_size=500": _page(
                [{"name": "r1"}], next_url="http://api.codecov.io/api/v2/github/acme/repos?page=2&page_size=500"
            ),
            # Codecov returns `next` links with an http:// scheme; we must follow them over https.
            "https://api.codecov.io/api/v2/github/acme/repos?page=2&page_size=500": _page([{"name": "r2"}]),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        rows = _collect(manager, repositories=None, endpoint="repos")

        assert [r["name"] for r in rows] == ["r1", "r2"]
        assert fetched == list(pages)
        # State is saved only while more pages remain, and after the page was yielded.
        assert manager.saved == [
            CodecovResumeConfig(next_url="https://api.codecov.io/api/v2/github/acme/repos?page=2&page_size=500")
        ]

    def test_repos_resumes_from_saved_url(self, monkeypatch: Any) -> None:
        resume_url = f"{_BASE}/repos?page=2&page_size=500"
        pages = {resume_url: _page([{"name": "r2"}])}
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(
            _FakeResumableManager(CodecovResumeConfig(next_url=resume_url)), repositories=None, endpoint="repos"
        )

        assert [r["name"] for r in rows] == ["r2"]
        assert fetched == [resume_url]

    def test_poisoned_next_url_aborts_the_sync(self, monkeypatch: Any) -> None:
        pages = {
            f"{_BASE}/repos?page_size=500": _page(
                [{"name": "r1"}], next_url="https://evil.example.com/api/v2/github/acme/repos?page=2"
            ),
        }
        _patch_fetch(monkeypatch, pages)

        with pytest.raises(ValueError):
            _collect(_FakeResumableManager(), repositories=None, endpoint="repos")

    def test_repos_applies_repository_allow_list(self, monkeypatch: Any) -> None:
        pages = {f"{_BASE}/repos?page_size=500": _page([{"name": "r1"}, {"name": "r2"}, {"name": "r3"}])}
        _patch_fetch(monkeypatch, pages)
        rows = _collect(_FakeResumableManager(), repositories="r1, r3", endpoint="repos")

        assert [r["name"] for r in rows] == ["r1", "r3"]


class TestFanOutRows:
    def test_fans_out_over_active_repos_and_injects_repo(self, monkeypatch: Any) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}]),
            f"{_BASE}/repos/r1/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 90.0}]),
            f"{_BASE}/repos/r2/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 80.0}]),
        }
        _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        rows = _collect(manager, repositories=None, endpoint="flags")

        assert [(r["repo"], r["flag_name"]) for r in rows] == [("r1", "unit"), ("r2", "unit")]
        # The bookmark advances to the next repo so a crash between repos resumes correctly.
        assert manager.saved == [CodecovResumeConfig(next_url=None, repo="r2")]

    def test_repository_allow_list_skips_repo_enumeration(self, monkeypatch: Any) -> None:
        pages = {f"{_BASE}/repos/r9/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 70.0}])}
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(_FakeResumableManager(), repositories="r9", endpoint="flags")

        assert [r["repo"] for r in rows] == ["r9"]
        assert _ACTIVE_REPOS_URL not in fetched

    def test_resumes_from_bookmarked_repo_and_url(self, monkeypatch: Any) -> None:
        resume_url = f"{_BASE}/repos/r2/flags?page=2&page_size=500"
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}, {"name": "r3"}]),
            resume_url: _page([{"flag_name": "unit", "coverage": 80.0}]),
            f"{_BASE}/repos/r3/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 60.0}]),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(
            _FakeResumableManager(CodecovResumeConfig(next_url=resume_url, repo="r2")),
            repositories=None,
            endpoint="flags",
        )

        # r1 was already synced; r2 resumes mid-pagination, r3 starts from its first page.
        assert [r["repo"] for r in rows] == ["r2", "r3"]
        assert f"{_BASE}/repos/r1/flags?page_size=500" not in fetched

    def test_missing_bookmarked_repo_starts_over(self, monkeypatch: Any) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 90.0}]),
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(
            _FakeResumableManager(CodecovResumeConfig(next_url="https://stale", repo="deleted-repo")),
            repositories=None,
            endpoint="flags",
        )

        assert [r["repo"] for r in rows] == ["r1"]

    def test_deleted_repo_404_is_skipped(self, monkeypatch: Any) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}]),
            f"{_BASE}/repos/r1/flags?page_size=500": _http_error(404),
            f"{_BASE}/repos/r2/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 80.0}]),
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(_FakeResumableManager(), repositories=None, endpoint="flags")

        assert [r["repo"] for r in rows] == ["r2"]

    def test_components_bare_list_endpoint(self, monkeypatch: Any) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/components": [{"component_id": "api", "name": "api", "coverage": 91.2}],
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(_FakeResumableManager(), repositories=None, endpoint="components")

        assert rows == [{"component_id": "api", "name": "api", "coverage": 91.2, "repo": "r1"}]


class TestIncrementalSync:
    _WATERMARK = datetime(2026, 7, 5, tzinfo=UTC)

    def test_commits_stop_paging_at_watermark_but_continue_to_next_repo(self, monkeypatch: Any) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}]),
            f"{_BASE}/repos/r1/commits?page_size=500": _page(
                [
                    {"commitid": "new", "timestamp": "2026-07-09T00:00:00Z"},
                    {"commitid": "old", "timestamp": "2026-07-01T00:00:00Z"},
                ],
                next_url=f"{_BASE}/repos/r1/commits?page=2&page_size=500",
            ),
            f"{_BASE}/repos/r2/commits?page_size=500": _page(
                [{"commitid": "other", "timestamp": "2026-07-08T00:00:00Z"}]
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        rows = _collect(
            manager,
            repositories=None,
            endpoint="commits",
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._WATERMARK,
        )

        # The boundary page is yielded in full (merge dedupes), then pagination stops for r1
        # while r2 still syncs.
        assert [r["commitid"] for r in rows] == ["new", "old", "other"]
        assert f"{_BASE}/repos/r1/commits?page=2&page_size=500" not in fetched
        # No page checkpoint is saved on a stopping page — only the repo bookmark.
        assert manager.saved == [CodecovResumeConfig(next_url=None, repo="r2")]

    def test_commits_without_watermark_page_through_everything(self, monkeypatch: Any) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/commits?page_size=500": _page(
                [{"commitid": "a", "timestamp": "2026-07-09T00:00:00Z"}],
                next_url=f"{_BASE}/repos/r1/commits?page=2&page_size=500",
            ),
            f"{_BASE}/repos/r1/commits?page=2&page_size=500": _page(
                [{"commitid": "b", "timestamp": "2020-01-01T00:00:00Z"}]
            ),
        }
        _patch_fetch(monkeypatch, pages)
        rows = _collect(
            _FakeResumableManager(),
            repositories=None,
            endpoint="commits",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert [r["commitid"] for r in rows] == ["a", "b"]

    def test_coverage_trend_uses_server_side_start_date(self, monkeypatch: Any) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/coverage?page_size=500&interval=1d&start_date=2026-07-05": _page(
                [{"timestamp": "2026-07-06T00:00:00Z", "min": 90.0, "max": 91.0, "avg": 90.5}]
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        rows = _collect(
            _FakeResumableManager(),
            repositories=None,
            endpoint="coverage_trend",
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._WATERMARK,
        )

        assert [r["repo"] for r in rows] == ["r1"]
        assert fetched == list(pages)

    def test_coverage_trend_full_refresh_has_no_start_date(self, monkeypatch: Any) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/coverage?page_size=500&interval=1d": _page(
                [{"timestamp": "2026-07-06T00:00:00Z", "min": 90.0, "max": 91.0, "avg": 90.5}]
            ),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        _collect(_FakeResumableManager(), repositories=None, endpoint="coverage_trend")

        assert fetched == list(pages)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, (True, 200)),
            ("bad_token", 401, (False, 401)),
            ("unknown_owner", 404, (False, 404)),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: tuple) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with mock.patch.object(codecov, "make_tracked_session", return_value=session):
            assert validate_credentials("token", "github", "acme") == expected

    def test_transport_error_maps_to_none(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(codecov, "make_tracked_session", return_value=session):
            assert validate_credentials("token", "github", "acme") == (False, None)
