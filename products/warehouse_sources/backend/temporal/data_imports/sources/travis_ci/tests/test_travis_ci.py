from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci import travis_ci
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.travis_ci import (
    TRAVIS_CI_BASE_URL,
    TravisCIResumeConfig,
    _resolve_page_url,
    get_rows,
    travis_ci_source,
    validate_credentials,
)

REPOS_URL = f"{TRAVIS_CI_BASE_URL}/repos?limit=100"
BUILDS_PARAMS = "limit=100&sort_by=id%3Adesc"
JOBS_PARAMS = "limit=100&sort_by=id%3Adesc&include=build.jobs"


def _page(collection_key: str, items: list[dict[str, Any]], next_path: str | None = None) -> dict[str, Any]:
    return {collection_key: items, "@pagination": {"next": {"@href": next_path} if next_path else None}}


class _FakeResumableManager:
    def __init__(self, state: TravisCIResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TravisCIResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TravisCIResumeConfig | None:
        return self._state

    def save_state(self, data: TravisCIResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager,
    pages: dict[str, dict[str, Any]],
    endpoint: str,
    logger: Any = None,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict[str, Any]:
        fetched.append(url)
        return pages[url]

    rows: list[dict[str, Any]] = []
    with (
        mock.patch.object(travis_ci, "make_tracked_session", lambda *a, **k: MagicMock()),
        mock.patch.object(travis_ci, "_fetch_page", fake_fetch),
    ):
        for batch in get_rows(
            api_token="tok",
            endpoint=endpoint,
            logger=logger if logger is not None else MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
    return rows, fetched


class TestRepositories:
    def test_follows_pagination_and_strips_meta_keys(self) -> None:
        page2_path = "/repos?limit=100&offset=100"
        pages = {
            REPOS_URL: _page(
                "repositories",
                [{"@type": "repository", "@href": "/repo/1", "id": 1, "slug": "o/a"}],
                next_path=page2_path,
            ),
            f"{TRAVIS_CI_BASE_URL}{page2_path}": _page("repositories", [{"id": 2, "slug": "o/b"}]),
        }
        manager = _FakeResumableManager()
        rows, fetched = _collect(manager, pages, endpoint="repositories")

        assert [r["id"] for r in rows] == [1, 2]
        assert "@type" not in rows[0] and "@href" not in rows[0]
        assert fetched == [REPOS_URL, f"{TRAVIS_CI_BASE_URL}{page2_path}"]
        # State is saved AFTER the page is yielded, pointing at the next page, so a crash
        # re-yields the in-progress page instead of skipping it.
        assert manager.saved == [TravisCIResumeConfig(next_path=page2_path)]

    def test_resumes_from_saved_page_path(self) -> None:
        resume_path = "/repos?limit=100&offset=200"
        pages = {f"{TRAVIS_CI_BASE_URL}{resume_path}": _page("repositories", [{"id": 9}])}
        manager = _FakeResumableManager(TravisCIResumeConfig(next_path=resume_path))
        rows, fetched = _collect(manager, pages, endpoint="repositories")

        assert fetched == [f"{TRAVIS_CI_BASE_URL}{resume_path}"]
        assert [r["id"] for r in rows] == [9]


class TestBuildsFanOut:
    def test_fans_out_over_repositories_and_bookmarks_progress(self) -> None:
        repo1_page2 = f"/repo/1/builds?{BUILDS_PARAMS}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}, {"id": 2}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{BUILDS_PARAMS}": _page(
                "builds", [{"@type": "build", "id": 30}, {"id": 20}], next_path=repo1_page2
            ),
            f"{TRAVIS_CI_BASE_URL}{repo1_page2}": _page("builds", [{"id": 10}]),
            f"{TRAVIS_CI_BASE_URL}/repo/2/builds?{BUILDS_PARAMS}": _page("builds", [{"id": 25}]),
        }
        manager = _FakeResumableManager()
        rows, _fetched = _collect(manager, pages, endpoint="builds")

        assert [(r["id"], r["repository_id"]) for r in rows] == [(30, 1), (20, 1), (10, 1), (25, 2)]
        assert manager.saved == [
            TravisCIResumeConfig(next_path=repo1_page2, repository_id=1),
            TravisCIResumeConfig(next_path=None, repository_id=2),
        ]

    @parameterized.expand([("int_watermark", 20), ("str_watermark", "20")])
    def test_incremental_stops_at_watermark(self, _name: str, watermark: Any) -> None:
        repo1_page2 = f"/repo/1/builds?{BUILDS_PARAMS}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}, {"id": 2}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{BUILDS_PARAMS}": _page(
                "builds", [{"id": 30}, {"id": 20}], next_path=repo1_page2
            ),
            f"{TRAVIS_CI_BASE_URL}/repo/2/builds?{BUILDS_PARAMS}": _page("builds", [{"id": 15}]),
        }
        rows, fetched = _collect(
            _FakeResumableManager(),
            pages,
            endpoint="builds",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        # Only builds newer than the watermark are yielded, and repo 1's older second page is
        # never fetched. Repo 2 is still scanned — the watermark is global, so each repo's scan
        # stops independently once it reaches already-synced builds.
        assert [r["id"] for r in rows] == [30]
        assert f"{TRAVIS_CI_BASE_URL}{repo1_page2}" not in fetched
        assert f"{TRAVIS_CI_BASE_URL}/repo/2/builds?{BUILDS_PARAMS}" in fetched

    def test_full_refresh_walks_all_pages(self) -> None:
        repo1_page2 = f"/repo/1/builds?{BUILDS_PARAMS}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{BUILDS_PARAMS}": _page("builds", [{"id": 30}], next_path=repo1_page2),
            f"{TRAVIS_CI_BASE_URL}{repo1_page2}": _page("builds", [{"id": 10}]),
        }
        rows, _fetched = _collect(_FakeResumableManager(), pages, endpoint="builds")
        assert [r["id"] for r in rows] == [30, 10]

    def test_resumes_from_bookmarked_repository(self) -> None:
        resume_path = f"/repo/2/builds?{BUILDS_PARAMS}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}, {"id": 2}, {"id": 3}]),
            f"{TRAVIS_CI_BASE_URL}{resume_path}": _page("builds", [{"id": 5}]),
            f"{TRAVIS_CI_BASE_URL}/repo/3/builds?{BUILDS_PARAMS}": _page("builds", [{"id": 7}]),
        }
        manager = _FakeResumableManager(TravisCIResumeConfig(next_path=resume_path, repository_id=2))
        rows, fetched = _collect(manager, pages, endpoint="builds")

        # Repo 1 is skipped entirely, repo 2 resumes at the saved page, repo 3 starts fresh.
        assert f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{BUILDS_PARAMS}" not in fetched
        assert [(r["id"], r["repository_id"]) for r in rows] == [(5, 2), (7, 3)]

    def test_missing_bookmarked_repository_starts_over(self) -> None:
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{BUILDS_PARAMS}": _page("builds", [{"id": 3}]),
        }
        manager = _FakeResumableManager(TravisCIResumeConfig(next_path="/repo/99/builds", repository_id=99))
        rows, _fetched = _collect(manager, pages, endpoint="builds")
        assert [r["id"] for r in rows] == [3]

    def test_page_cap_stops_pagination_and_warns(self) -> None:
        repo1_page2 = f"/repo/1/builds?{BUILDS_PARAMS}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{BUILDS_PARAMS}": _page("builds", [{"id": 30}], next_path=repo1_page2),
        }
        logger = MagicMock()
        with mock.patch.object(travis_ci, "MAX_PAGES_PER_REPO", 1):
            rows, fetched = _collect(_FakeResumableManager(), pages, endpoint="builds", logger=logger)

        assert [r["id"] for r in rows] == [30]
        assert f"{TRAVIS_CI_BASE_URL}{repo1_page2}" not in fetched
        logger.warning.assert_called_once()


class TestJobs:
    def test_flattens_embedded_jobs_with_parent_identifiers(self) -> None:
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{JOBS_PARAMS}": _page(
                "builds",
                [
                    {
                        "id": 30,
                        "jobs": [
                            {"@type": "job", "id": 301, "state": "passed", "build": {"@type": "build", "id": 30}},
                            {"id": 302, "state": "failed"},
                        ],
                    },
                    {"id": 20, "jobs": []},
                ],
            ),
        }
        rows, _fetched = _collect(_FakeResumableManager(), pages, endpoint="jobs")

        assert [(r["id"], r["build_id"], r["repository_id"]) for r in rows] == [(301, 30, 1), (302, 30, 1)]
        # Meta keys are stripped recursively, including from nested minimal representations.
        assert "@type" not in rows[0]
        assert "@type" not in rows[0]["build"]

    def test_incremental_stops_at_build_watermark(self) -> None:
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{JOBS_PARAMS}": _page(
                "builds",
                [
                    {"id": 30, "jobs": [{"id": 301}]},
                    {"id": 20, "jobs": [{"id": 201}]},
                ],
                next_path=f"/repo/1/builds?{JOBS_PARAMS}&offset=100",
            ),
        }
        rows, fetched = _collect(
            _FakeResumableManager(),
            pages,
            endpoint="jobs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=20,
        )

        assert [r["id"] for r in rows] == [301]
        assert len(fetched) == 2  # /repos + first builds page; the older page is never fetched


class TestBranches:
    def test_rows_carry_composite_primary_key_fields(self) -> None:
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/branches?limit=100": _page(
                "branches", [{"@type": "branch", "name": "main", "default_branch": True}]
            ),
        }
        rows, _fetched = _collect(_FakeResumableManager(), pages, endpoint="branches")
        assert rows == [{"name": "main", "default_branch": True, "repository_id": 1}]


class TestPaginationCursorValidation:
    @parameterized.expand(
        [
            ("relative_path", "/repos?limit=100&offset=100", f"{TRAVIS_CI_BASE_URL}/repos?limit=100&offset=100"),
            ("bare_path", "/user", f"{TRAVIS_CI_BASE_URL}/user"),
        ]
    )
    def test_accepts_relative_cursor(self, _name: str, cursor: str, expected: str) -> None:
        assert _resolve_page_url(cursor) == expected

    @parameterized.expand(
        [
            # A userinfo-smuggling cursor: concatenation makes the API host the userinfo and the
            # attacker host the real host, exfiltrating the Authorization header.
            ("userinfo_smuggle", "@attacker.example/next"),
            ("scheme_relative", "//attacker.example/next"),
            ("absolute_url", "https://attacker.example/next"),
            ("leading_space", " /repos"),
            ("no_leading_slash", "repos?limit=100"),
        ]
    )
    def test_rejects_host_changing_cursor(self, _name: str, cursor: str) -> None:

        with pytest.raises(ValueError):
            _resolve_page_url(cursor)


class TestHostileCursorFailsSync:
    def test_hostile_next_cursor_from_upstream_raises(self) -> None:

        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}], next_path="@attacker.example/next"),
        }
        with pytest.raises(ValueError):
            _collect(_FakeResumableManager(), pages, endpoint="repositories")

    def test_hostile_resume_cursor_raises(self) -> None:

        manager = _FakeResumableManager(TravisCIResumeConfig(next_path="@attacker.example/next"))
        with pytest.raises(ValueError):
            _collect(manager, {}, endpoint="repositories")


class TestRedirectsDisabled:
    def test_sessions_disable_redirects(self) -> None:
        # allow_redirects=False keeps a poisoned cursor or hostile response from bouncing the
        # credentialed request (and its token) to another host — defense in depth alongside
        # cursor validation.
        made: list[dict[str, Any]] = []

        def fake_make(*_args: Any, **kwargs: Any) -> MagicMock:
            made.append(kwargs)
            return MagicMock()

        with mock.patch.object(travis_ci, "make_tracked_session", fake_make):
            validate_credentials("tok")
        assert made and all(call.get("allow_redirects") is False for call in made)


class _FakeResponse:
    def __init__(self, status_code: int, body: Any = None) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = ""

    def json(self) -> Any:
        return self._body


class TestValidateCredentials:
    @staticmethod
    def _validate_with(response_or_error: Any) -> tuple[bool, str | None]:
        session = MagicMock()
        if isinstance(response_or_error, Exception):
            session.get.side_effect = response_or_error
        else:
            session.get.return_value = response_or_error
        with mock.patch.object(travis_ci, "make_tracked_session", lambda *a, **k: session):
            return validate_credentials("tok")

    @parameterized.expand(
        [
            ("valid", 200, True),
            # Travis answers 403 "access denied" for missing/invalid tokens (it has no scopes),
            # so a 403 means the token is bad — unlike sources where 403 = missing scope.
            ("access_denied", 403, False),
            ("unauthorized", 401, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        ok, error = self._validate_with(_FakeResponse(status_code, {"error_message": "boom"}))
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_network_error_is_reported_not_raised(self) -> None:
        ok, error = self._validate_with(requests.ConnectionError("boom"))
        assert ok is False
        assert error is not None and "Travis CI" in error


class TestTravisCISourceResponse:
    @parameterized.expand(
        [
            ("repositories", ["id"], None),
            ("builds", ["id"], None),
            ("jobs", ["id"], "created_at"),
            ("branches", ["repository_id", "name"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        response = travis_ci_source(
            api_token="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "desc"
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
