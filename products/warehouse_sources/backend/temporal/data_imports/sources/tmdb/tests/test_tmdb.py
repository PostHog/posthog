from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tmdb import TMDbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.source import TMDbSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.tmdb import (
    TMDbResumeConfig,
    validate_credentials,
)


def _page_response(rows: list[dict[str, Any]], *, page: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(json={"page": page, "results": rows, "total_pages": total_pages})


def _source(endpoint: str, script: Script, resume: TMDbResumeConfig | None = None, api_key: str = "k") -> DriveResult:
    driver = SourceDriver(TMDbSource(), TMDbSourceConfig(api_key=api_key))
    return driver.run(endpoint, script, resume_state=resume)


class TestPagination:
    def test_paginates_until_total_pages_and_saves_state(self) -> None:
        result = _source(
            "movie_popular",
            [
                _page_response([{"id": 1}], page=1, total_pages=2),
                _page_response([{"id": 2}], page=2, total_pages=2),
            ],
        )

        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.params("page") == ["1", "2"]
        assert result.requests[0].param("language") == "en-US"
        # State saved after the first page only (the last page has nothing more to resume to).
        assert result.saved_states == [TMDbResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _source(
            "movie_popular",
            [_page_response([{"id": 5}], page=5, total_pages=5)],
            resume=TMDbResumeConfig(next_page=5),
        )

        assert result.rows == [{"id": 5}]
        # Picks up at page 5, not page 1, and never checkpoints again.
        assert result.params("page") == ["5"]
        assert result.saved_states == []


class TestNonPaginatedEndpoints:
    def test_bare_list_endpoint_yields_rows(self) -> None:
        result = _source("languages", [ScriptedResponse(json=[{"iso_639_1": "en", "name": "English"}])])

        assert result.rows == [{"iso_639_1": "en", "name": "English"}]
        assert result.saved_states == []


class TestErrorRedaction:
    def test_401_scrubs_api_key_but_preserves_host(self) -> None:
        # The api_key rides in the query string; a 4xx must not leak it into the propagated error,
        # while the base host stays intact so get_non_retryable_errors() can still match on it.
        result = _source(
            "movie_popular", [ScriptedResponse(status=401, json={"status_code": 7})], api_key="supersecret"
        )

        assert isinstance(result.raised, requests.HTTPError)
        message = str(result.raised)
        assert "supersecret" not in message
        assert "https://api.themoviedb.org/3/movie/popular" in message


class TestValidateCredentials:
    def test_valid_key_returns_no_message(self) -> None:
        with scripted_network([ScriptedResponse(json={})]):
            assert validate_credentials("k") == (True, None)

    def test_401_reports_invalid_key(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={})]):
            assert validate_credentials("k") == (False, "Invalid TMDB API key")

    @pytest.mark.parametrize("status", [404, 429, 500, 503])
    def test_non_401_failure_does_not_claim_invalid_key(self, status: int) -> None:
        # A transient/service-side failure must not be reported as an invalid credential.
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message is not None
        assert message != "Invalid TMDB API key"

    def test_network_error_does_not_claim_invalid_key(self) -> None:
        with scripted_network(always(ConnectionResetError("reset"))):
            is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message is not None
        assert message != "Invalid TMDB API key"
