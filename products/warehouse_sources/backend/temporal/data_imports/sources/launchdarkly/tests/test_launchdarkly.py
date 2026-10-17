from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.launchdarkly import (
    LaunchDarklySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly import (
    API_HOST,
    BASE_URL,
    LaunchDarklyResumeConfig,
    _resolve_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.settings import (
    ENDPOINTS,
    LAUNCHDARKLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source import LaunchDarklySource


def _driver() -> SourceDriver:
    return SourceDriver(LaunchDarklySource(), LaunchDarklySourceConfig(access_token="token"))


def _page(items: list[dict[str, Any]], next_href: str | None = None) -> ScriptedResponse:
    links = {"next": {"href": next_href}} if next_href else {}
    return ScriptedResponse(json={"items": items, "_links": links})


class TestUrlHelpers:
    @pytest.mark.parametrize(
        "href, expected",
        [
            ("/api/v2/projects?limit=20&offset=20", f"{API_HOST}/api/v2/projects?limit=20&offset=20"),
            ("https://app.launchdarkly.com/api/v2/members?offset=40", f"{API_HOST}/api/v2/members?offset=40"),
        ],
    )
    def test_resolve_url(self, href: str, expected: str) -> None:
        assert _resolve_url(href) == expected


class TestValidateCredentials:
    def test_returns_none_on_exception(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("api-token") is None

        assert {request.path for request in network.requests_log} == {"/api/v2/caller-identity"}


class TestGetRowsTopLevel:
    def test_paginates_via_links_next(self) -> None:
        next_url = f"{API_HOST}/api/v2/members?limit=20&offset=20"
        result = _driver().run(
            "members",
            [_page([{"_id": "1"}, {"_id": "2"}], "/api/v2/members?limit=20&offset=20"), _page([{"_id": "3"}])],
        )

        assert result.raised is None
        assert [item["_id"] for item in result.rows] == ["1", "2", "3"]
        # No project key injected for top-level endpoints.
        assert all("_project_key" not in item for item in result.rows)
        # First page targets the base path; second follows the (resolved) _links.next href.
        assert result.requests[0].path == "/api/v2/members"
        assert result.requests[0].param("limit") == "20"
        assert result.requests[1].url == next_url
        # One checkpoint, saved after the first page (points at the next URL); the last page saves none.
        assert result.saved_states == [LaunchDarklyResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = f"{API_HOST}/api/v2/members?limit=20&offset=80"
        result = _driver().run(
            "members", [_page([{"_id": "9"}])], resume_state=LaunchDarklyResumeConfig(next_url=resume_url)
        )

        assert result.raised is None
        assert result.urls == [resume_url]


class TestGetRowsFanout:
    def test_iterates_projects_and_injects_project_key(self) -> None:
        result = _driver().run(
            "environments",
            [_page([{"key": "proj1"}, {"key": "proj2"}]), _page([{"_id": "e1"}]), _page([{"_id": "e2"}])],
        )

        assert result.raised is None
        assert result.rows == [
            {"_id": "e1", "_project_key": "proj1"},
            {"_id": "e2", "_project_key": "proj2"},
        ]
        assert result.paths == [
            "/api/v2/projects",
            "/api/v2/projects/proj1/environments",
            "/api/v2/projects/proj2/environments",
        ]

    def test_resume_midproject_uses_saved_url(self) -> None:
        resume_url = f"{BASE_URL}/projects/proj1/environments?limit=20&offset=20"
        result = _driver().run(
            "environments",
            [_page([{"key": "proj1"}, {"key": "proj2"}]), _page([{"_id": "e1b"}]), _page([{"_id": "e2"}])],
            resume_state=LaunchDarklyResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/projects/proj1/environments",
                    "child_state": {"next_url": resume_url},
                }
            ),
        )

        assert result.raised is None
        assert result.requests[0].path == "/api/v2/projects"
        assert result.requests[1].url == resume_url
        assert result.requests[2].path == "/api/v2/projects/proj2/environments"


class TestGetRowsEnvironmentFanout:
    def test_iterates_environments_of_every_project_and_injects_both_keys(self) -> None:
        next_url = f"{API_HOST}/api/v2/segments/proj1/prod?limit=20&offset=20&sort=creationDate"
        result = _driver().run(
            "segments",
            [
                _page([{"key": "proj1"}]),
                _page([{"key": "prod"}, {"key": "dev"}]),
                _page([{"key": "s1"}], "/api/v2/segments/proj1/prod?limit=20&offset=20&sort=creationDate"),
                _page([{"key": "s2"}]),
                _page([{"key": "s3"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"key": "s1", "_environment_key": "prod", "_project_key": "proj1"},
            {"key": "s2", "_environment_key": "prod", "_project_key": "proj1"},
            {"key": "s3", "_environment_key": "dev", "_project_key": "proj1"},
        ]
        assert result.requests[0].path == "/api/v2/projects"
        assert result.requests[1].path == "/api/v2/projects/proj1/environments"
        assert result.requests[2].path == "/api/v2/segments/proj1/prod"
        assert result.requests[3].url == next_url
        assert result.requests[4].path == "/api/v2/segments/proj1/dev"
        assert result.requests[2].param("limit") == "20"
        assert result.requests[2].param("sort") == "creationDate"

    def test_flag_statuses_take_flag_key_from_self_link(self) -> None:
        status = {
            "name": "inactive",
            "_links": {
                "parent": {"href": "/api/v2/flags/proj1/my-flag"},
                "self": {"href": "/api/v2/flag-statuses/proj1/prod/my-flag"},
            },
        }
        result = _driver().run("flag_statuses", [_page([{"key": "proj1"}]), _page([{"key": "prod"}]), _page([status])])

        assert result.raised is None
        assert [(row["_flag_key"], row["_project_key"], row["_environment_key"]) for row in result.rows] == [
            ("my-flag", "proj1", "prod")
        ]
        assert result.requests[2].path == "/api/v2/flag-statuses/proj1/prod"
        assert result.requests[2].param("limit") is None

    def test_resume_skips_completed_environments(self) -> None:
        resume_url = f"{BASE_URL}/projects/proj1/environments/dev/holdouts?limit=20&offset=20"
        result = _driver().run(
            "holdouts",
            [_page([{"key": "proj1"}]), _page([{"key": "prod"}, {"key": "dev"}]), _page([{"_id": "h2"}])],
            resume_state=LaunchDarklyResumeConfig(
                fanout_state={
                    "completed": ["/projects/proj1/environments/prod/holdouts"],
                    "current": "/projects/proj1/environments/dev/holdouts",
                    "child_state": {"next_url": resume_url},
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"_id": "h2", "_environment_key": "dev", "_project_key": "proj1"}]
        assert result.requests[0].path == "/api/v2/projects"
        assert result.requests[1].path == "/api/v2/projects/proj1/environments"
        assert result.requests[2].url == resume_url


class TestRetryAndErrors:
    def test_4xx_raises(self) -> None:
        result = _driver().run("members", [ScriptedResponse(status=403, json={"items": []})])

        assert isinstance(result.raised, Exception)
        assert "403 Client Error" in str(result.raised)


class TestLaunchDarklySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = LAUNCHDARKLY_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, always(_page([])))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_key
        # Partitioning is intentionally off (epoch-ms timestamps).
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
