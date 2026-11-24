from collections.abc import Callable, Mapping
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    scripted_network,
)
from products.warehouse_sources.sources.travis_ci import travis_ci
from products.warehouse_sources.sources.travis_ci._config import TravisCISourceConfig
from products.warehouse_sources.sources.travis_ci.source import TravisCISource
from products.warehouse_sources.sources.travis_ci.travis_ci import (
    TRAVIS_CI_BASE_URL,
    TravisCIResumeConfig,
    _resolve_page_url,
    validate_credentials,
)

REPOS_URL = f"{TRAVIS_CI_BASE_URL}/repos?limit=100"
BUILDS_PARAMS = "limit=100&sort_by=id%3Adesc"
JOBS_PARAMS = "limit=100&sort_by=id%3Adesc&include=build.jobs"
REQUESTS_PARAMS = "limit=100"
CRONS_PARAMS = "limit=100"
ORGS_URL = f"{TRAVIS_CI_BASE_URL}/orgs?limit=100&sort_by=id"


def _page(collection_key: str, items: list[dict[str, Any]], next_path: str | None = None) -> dict[str, Any]:
    return {collection_key: items, "@pagination": {"next": {"@href": next_path} if next_path else None}}


def _serve(pages: Mapping[str, dict[str, Any] | ScriptedResponse]) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.url not in pages:
            raise UnexpectedRequest(f"no page scripted for {request.url}")
        page = pages[request.url]
        return page if isinstance(page, ScriptedResponse) else ScriptedResponse(json=page)

    return respond


def _collect(
    pages: Mapping[str, dict[str, Any] | ScriptedResponse],
    endpoint: str,
    resume_state: TravisCIResumeConfig | None = None,
    **kwargs: Any,
) -> DriveResult:
    driver = SourceDriver(TravisCISource(), TravisCISourceConfig(api_token="tok"))
    return driver.run(endpoint, _serve(pages), resume_state=resume_state, **kwargs)


class TestTopLevelEndpoints:
    @parameterized.expand(
        [
            ("repositories", REPOS_URL, "/repos?limit=100&offset=100"),
            ("organizations", ORGS_URL, "/orgs?limit=100&sort_by=id&offset=100"),
        ]
    )
    def test_follows_pagination_and_strips_meta_keys(self, endpoint: str, first_url: str, page2_path: str) -> None:
        pages: dict[str, dict[str, Any] | ScriptedResponse] = {
            first_url: _page(
                endpoint,
                [{"@type": endpoint[:-1], "@href": "/x/1", "id": 1, "login": "a"}],
                next_path=page2_path,
            ),
            f"{TRAVIS_CI_BASE_URL}{page2_path}": _page(endpoint, [{"id": 2, "login": "b"}]),
        }
        result = _collect(pages, endpoint=endpoint)

        assert result.raised is None
        assert result.rows == [{"id": 1, "login": "a"}, {"id": 2, "login": "b"}]
        assert result.urls == [first_url, f"{TRAVIS_CI_BASE_URL}{page2_path}"]
        # State is saved AFTER the page is yielded, pointing at the next page, so a crash
        # re-yields the in-progress page instead of skipping it.
        assert result.saved_states == [TravisCIResumeConfig(next_path=page2_path)]


class TestBuildsFanOut:
    @parameterized.expand(
        [
            ("builds_int_watermark", "builds", BUILDS_PARAMS, 20),
            ("builds_str_watermark", "builds", BUILDS_PARAMS, "20"),
            ("requests", "requests", REQUESTS_PARAMS, 20),
        ]
    )
    def test_incremental_stops_at_watermark(self, _name: str, endpoint: str, params: str, watermark: Any) -> None:
        repo1_page2 = f"/repo/1/{endpoint}?{params}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}, {"id": 2}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/{endpoint}?{params}": _page(
                endpoint, [{"id": 30}, {"id": 20}], next_path=repo1_page2
            ),
            f"{TRAVIS_CI_BASE_URL}/repo/2/{endpoint}?{params}": _page(endpoint, [{"id": 15}]),
        }
        result = _collect(
            pages,
            endpoint=endpoint,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        # Only rows newer than the watermark are yielded, and repo 1's older second page is
        # never fetched. Repo 2 is still scanned — the watermark is global, so each repo's scan
        # stops independently once it reaches already-synced rows.
        assert [r["id"] for r in result.rows] == [30]
        assert f"{TRAVIS_CI_BASE_URL}{repo1_page2}" not in result.urls
        assert f"{TRAVIS_CI_BASE_URL}/repo/2/{endpoint}?{params}" in result.urls

    @parameterized.expand([("requests", REQUESTS_PARAMS), ("crons", CRONS_PARAMS)])
    def test_full_refresh_walks_every_page_of_every_repo(self, endpoint: str, params: str) -> None:
        repo1_page2 = f"/repo/1/{endpoint}?{params}&offset=100"
        pages = {
            REPOS_URL: _page("repositories", [{"id": 1}, {"id": 2}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/{endpoint}?{params}": _page(
                endpoint, [{"@type": endpoint[:-1], "id": 30}], next_path=repo1_page2
            ),
            f"{TRAVIS_CI_BASE_URL}{repo1_page2}": _page(endpoint, [{"id": 20}]),
            f"{TRAVIS_CI_BASE_URL}/repo/2/{endpoint}?{params}": _page(endpoint, [{"id": 15}]),
        }
        result = _collect(pages, endpoint=endpoint)

        assert result.raised is None
        assert result.rows == [
            {"id": 30, "repository_id": 1},
            {"id": 20, "repository_id": 1},
            {"id": 15, "repository_id": 2},
        ]

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


class TestEmbeddedRows:
    @parameterized.expand(
        [
            ("jobs", "builds", JOBS_PARAMS, "build_id"),
            ("stages", "builds", BUILDS_PARAMS, "build_id"),
            ("messages", "requests", REQUESTS_PARAMS, "request_id"),
        ]
    )
    def test_incremental_stops_at_parent_watermark(
        self, endpoint: str, parent: str, params: str, parent_key: str
    ) -> None:
        pages: dict[str, dict[str, Any] | ScriptedResponse] = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/{parent}?{params}": _page(
                parent,
                [
                    {"id": 30, endpoint: [{"@type": endpoint[:-1], "id": 301}, {"id": 302}]},
                    {"id": 25, endpoint: []},
                    {"id": 20, endpoint: [{"id": 201}]},
                ],
                next_path=f"/repo/1/{parent}?{params}&offset=100",
            ),
        }
        result = _collect(
            pages,
            endpoint=endpoint,
            should_use_incremental_field=True,
            db_incremental_field_last_value=20,
        )

        assert result.rows == [
            {"id": 301, parent_key: 30, "repository_id": 1},
            {"id": 302, parent_key: 30, "repository_id": 1},
        ]
        assert len(result.urls) == 2  # /repos + first parent page; the older page is never fetched


class TestForbiddenRepositories:
    def test_caches_skip_forbidden_repository_and_send_no_paging_params(self) -> None:
        cache = {"repository_id": 2, "branch": "main", "name": "cache-linux.tgz", "size": 1024}
        pages: dict[str, dict[str, Any] | ScriptedResponse] = {
            REPOS_URL: _page("repositories", [{"id": 1}, {"id": 2}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/caches": ScriptedResponse(
                status=403, json={"error_type": "insufficient_access"}
            ),
            f"{TRAVIS_CI_BASE_URL}/repo/2/caches": {"@type": "caches", "caches": [{"@type": "cache", **cache}]},
        }
        result = _collect(pages, endpoint="caches")

        assert result.raised is None
        assert result.rows == [cache]

    def test_forbidden_repository_fails_other_endpoints(self) -> None:
        pages: dict[str, dict[str, Any] | ScriptedResponse] = {
            REPOS_URL: _page("repositories", [{"id": 1}]),
            f"{TRAVIS_CI_BASE_URL}/repo/1/crons?{CRONS_PARAMS}": ScriptedResponse(
                status=403, json={"error_type": "insufficient_access"}
            ),
        }
        result = _collect(pages, endpoint="crons")

        assert isinstance(result.raised, requests.HTTPError)


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
            ("stages", ["id"], None),
            ("requests", ["id"], "created_at"),
            ("crons", ["id"], "created_at"),
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
