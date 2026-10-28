from collections.abc import Callable
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.travisci import (
    TravisCISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci import travis_ci
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.source import TravisCISource
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.travis_ci import (
    TRAVIS_CI_BASE_URL,
    TravisCIResumeConfig,
    _resolve_page_url,
    validate_credentials,
)

REPOS_URL = f"{TRAVIS_CI_BASE_URL}/repos?limit=100"
BUILDS_PARAMS = "limit=100&sort_by=id%3Adesc"
JOBS_PARAMS = "limit=100&sort_by=id%3Adesc&include=build.jobs"


def _page(collection_key: str, items: list[dict[str, Any]], next_path: str | None = None) -> dict[str, Any]:
    return {collection_key: items, "@pagination": {"next": {"@href": next_path} if next_path else None}}


def _serve(pages: dict[str, dict[str, Any]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.url not in pages:
            raise UnexpectedRequest(f"no page scripted for {request.url}")
        return ScriptedResponse(json=pages[request.url])

    return respond


def _collect(
    pages: dict[str, dict[str, Any]],
    endpoint: str,
    resume_state: TravisCIResumeConfig | None = None,
    **kwargs: Any,
) -> DriveResult:
    driver = SourceDriver(TravisCISource(), TravisCISourceConfig(api_token="tok"))
    return driver.run(endpoint, _serve(pages), resume_state=resume_state, **kwargs)


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
        result = _collect(pages, endpoint="repositories")

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [1, 2]
        assert "@type" not in result.rows[0] and "@href" not in result.rows[0]
        assert result.urls == [REPOS_URL, f"{TRAVIS_CI_BASE_URL}{page2_path}"]
        # State is saved AFTER the page is yielded, pointing at the next page, so a crash
        # re-yields the in-progress page instead of skipping it.
        assert result.saved_states == [TravisCIResumeConfig(next_path=page2_path)]


class TestBuildsFanOut:
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
        result = _collect(
            pages,
            endpoint="builds",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        # Only builds newer than the watermark are yielded, and repo 1's older second page is
        # never fetched. Repo 2 is still scanned — the watermark is global, so each repo's scan
        # stops independently once it reaches already-synced builds.
        assert [r["id"] for r in result.rows] == [30]
        assert f"{TRAVIS_CI_BASE_URL}{repo1_page2}" not in result.urls
        assert f"{TRAVIS_CI_BASE_URL}/repo/2/builds?{BUILDS_PARAMS}" in result.urls

    def test_resumes_from_bookmarked_repository(self) -> None:
        resume_path = f"/repo/2/builds?{BUILDS_PARAMS}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}, {"id": 2}, {"id": 3}]),
            f"{TRAVIS_CI_BASE_URL}{resume_path}": _page("builds", [{"id": 5}]),
            f"{TRAVIS_CI_BASE_URL}/repo/3/builds?{BUILDS_PARAMS}": _page("builds", [{"id": 7}]),
        }
        result = _collect(
            pages, endpoint="builds", resume_state=TravisCIResumeConfig(next_path=resume_path, repository_id=2)
        )

        # Repo 1 is skipped entirely, repo 2 resumes at the saved page, repo 3 starts fresh.
        assert f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{BUILDS_PARAMS}" not in result.urls
        assert [(r["id"], r["repository_id"]) for r in result.rows] == [(5, 2), (7, 3)]

    def test_page_cap_stops_pagination_and_warns(self) -> None:
        repo1_page2 = f"/repo/1/builds?{BUILDS_PARAMS}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/builds?{BUILDS_PARAMS}": _page("builds", [{"id": 30}], next_path=repo1_page2),
        }
        logger = MagicMock()
        with mock.patch.object(travis_ci, "MAX_PAGES_PER_REPO", 1):
            result = _collect(pages, endpoint="builds", logger=logger)

        assert [r["id"] for r in result.rows] == [30]
        assert f"{TRAVIS_CI_BASE_URL}{repo1_page2}" not in result.urls
        logger.warning.assert_called_once()


class TestJobs:
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
        result = _collect(
            pages,
            endpoint="jobs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=20,
        )

        assert [r["id"] for r in result.rows] == [301]
        assert len(result.urls) == 2  # /repos + first builds page; the older page is never fetched


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
        result = _collect(pages, endpoint="repositories")
        assert isinstance(result.raised, ValueError)

    def test_hostile_resume_cursor_raises(self) -> None:
        result = _collect(
            {}, endpoint="repositories", resume_state=TravisCIResumeConfig(next_path="@attacker.example/next")
        )
        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestRedirectsDisabled:
    def test_sessions_disable_redirects(self) -> None:
        # allow_redirects=False keeps a poisoned cursor or hostile response from bouncing the
        # credentialed request (and its token) to another host — defense in depth alongside
        # cursor validation.
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("tok")
        assert network.session_options and all(call.get("allow_redirects") is False for call in network.session_options)


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
        response = _collect({}, endpoint=endpoint).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "desc"
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
