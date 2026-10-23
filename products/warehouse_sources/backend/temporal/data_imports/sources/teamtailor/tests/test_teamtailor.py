from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamtailor import (
    TeamtailorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor import teamtailor
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.settings import (
    ENDPOINTS,
    TEAMTAILOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.source import TeamtailorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.teamtailor import (
    API_VERSION_20240404,
    API_VERSION_20240904,
    SUPPORTED_API_VERSIONS,
    TeamtailorResumeConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(TeamtailorSource(), TeamtailorSourceConfig(api_key="tt-key"))


def _page(rows: list[dict], next_url: str | None = None, status: int = 200) -> ScriptedResponse:
    body: dict[str, Any] = {"data": rows, "links": {"next": next_url} if next_url else {}, "meta": {}}
    return ScriptedResponse(status=status, json=body)


def _raw(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


class TestPagination:
    def test_follows_next_link_verbatim_until_null(self) -> None:
        next_url = "https://api.teamtailor.com/v1/candidates?page%5Bnumber%5D=2"
        result = _driver().run(
            "candidates",
            [_page([{"id": "1"}], next_url=next_url), _page([{"id": "2"}], next_url=None)],
        )

        assert result.rows == [{"id": "1"}, {"id": "2"}]
        # First request carries the page[size] param; the second follows the `next` URL verbatim,
        # with no first-page params re-appended.
        assert result.urls[0].startswith("https://api.teamtailor.com/v1/candidates?page%5Bsize%5D=30")
        assert result.urls[1] == next_url
        # Saved after page 1 (a next page remains), never after the final page.
        assert result.saved_states == [TeamtailorResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_cursor(self) -> None:
        resume_url = "https://api.teamtailor.com/v1/candidates?page%5Bnumber%5D=3"
        result = _driver().run(
            "candidates",
            [_page([{"id": "9"}], next_url=None)],
            resume_state=TeamtailorResumeConfig(next_url=resume_url),
        )

        assert result.rows == [{"id": "9"}]
        # The first fetch follows the saved cursor, never re-requesting the first page.
        assert result.urls == [resume_url]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_retried_then_reraised(self, _name: str, status: int) -> None:
        result = _driver().run("candidates", always(_raw({"errors": []}, status=status)))
        assert isinstance(result.raised, RESTClientRetryableError)
        # The client retries transient statuses up to its default attempt cap before giving up.
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_fail_permanently_without_retry(self, _name: str, status: int) -> None:
        result = _driver().run("candidates", always(_raw({"errors": []}, status=status)))
        assert isinstance(result.raised, requests.HTTPError)
        # Auth/not-found failures are permanent — the request is issued exactly once.
        assert len(result.requests) == 1

    def test_non_list_body_is_retried(self) -> None:
        # JSON:API always wraps rows under `data`; a bare-array (or otherwise misshapen) 200 body is
        # treated as a transient malformed payload and retried rather than ingested as rows.
        result = _driver().run("candidates", always(_raw([{"id": "1"}], status=200)))
        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5


class TestAuthHeaders:
    @parameterized.expand([(v,) for v in SUPPORTED_API_VERSIONS])
    def test_headers_carry_token_and_requested_api_version(self, api_version: str) -> None:
        headers = teamtailor._headers("tt-key", api_version)
        assert headers["Authorization"] == "Token token=tt-key"
        assert headers["X-Api-Version"] == api_version
        assert headers["Accept"] == "application/vnd.api+json"

    @parameterized.expand([(v,) for v in SUPPORTED_API_VERSIONS])
    def test_version_headers_carry_no_secret(self, api_version: str) -> None:
        # The API key travels via the framework auth config, not these static headers.
        headers = teamtailor._version_headers(api_version)
        assert "Authorization" not in headers
        assert headers["X-Api-Version"] == api_version

    @parameterized.expand([("legacy", API_VERSION_20240404), ("current", API_VERSION_20240904)])
    def test_requested_api_version_reaches_the_wire(self, _name: str, api_version: str) -> None:
        result = _driver().run("candidates", [_page([{"id": "1"}], next_url=None)], api_version=api_version)

        headers = result.requests[0].headers
        assert headers["authorization"] == "Token token=tt-key"
        assert headers["x-api-version"] == api_version


class TestTeamtailorSourceResponse:
    @parameterized.expand(
        [
            ("candidates", "/v1/candidates"),
            ("jobs", "/v1/jobs"),
            ("job_applications", "/v1/job-applications"),
            ("users", "/v1/users"),
            ("departments", "/v1/departments"),
            ("stages", "/v1/stages"),
            ("movements", "/v1/movements"),
            ("reject_reasons", "/v1/reject-reasons"),
            ("locations", "/v1/locations"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_path: str) -> None:
        result = _driver().run(endpoint, always(_page([{"id": "1"}])))
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        # Table names use underscores, but Teamtailor paths are kebab-case.
        assert result.paths == [expected_path]
        assert result.rows == [{"id": "1"}]

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in TEAMTAILOR_ENDPOINTS.values())
        assert set(TEAMTAILOR_ENDPOINTS) == set(ENDPOINTS)
