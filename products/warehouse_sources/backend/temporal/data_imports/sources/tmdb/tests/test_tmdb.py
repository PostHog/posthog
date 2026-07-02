import json
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb import tmdb as tmdb_module
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.settings import TMDB_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.tmdb import (
    TMDbResumeConfig,
    _build_url,
    _extract_rows,
    get_rows,
    tmdb_source,
    validate_credentials,
)


def _make_response(status_code: int, body: Any) -> requests.Response:
    # A real Response so .json(), .ok, and .raise_for_status() behave exactly like production.
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://api.themoviedb.org/3/x"
    response._content = json.dumps(body).encode()
    return response


def _fake_session(responses: list[requests.Response]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = responses
    return session


def _make_manager(resume: TMDbResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tmdb_module, "THROTTLE_SECONDS", 0)


class TestExtractRows:
    @pytest.mark.parametrize(
        "endpoint, body, expected",
        [
            ("movie_popular", {"page": 1, "results": [{"id": 1}], "total_pages": 1}, [{"id": 1}]),
            ("movie_genres", {"genres": [{"id": 28, "name": "Action"}]}, [{"id": 28, "name": "Action"}]),
            ("languages", [{"iso_639_1": "en", "name": "English"}], [{"iso_639_1": "en", "name": "English"}]),
            # Defensive: wrong-typed payloads degrade to empty rather than raising.
            ("movie_popular", {"results": None}, []),
            ("languages", {"unexpected": "object"}, []),
        ],
    )
    def test_extract_rows(self, endpoint: str, body: Any, expected: list) -> None:
        assert _extract_rows(body, TMDB_ENDPOINTS[endpoint]) == expected


class TestBuildUrl:
    def test_paginated_url_includes_page_and_language(self) -> None:
        url = _build_url("/movie/popular", "secret", page=3)
        assert url.startswith("https://api.themoviedb.org/3/movie/popular?")
        assert "api_key=secret" in url
        assert "page=3" in url
        assert "language=en-US" in url

    def test_non_paginated_url_omits_page(self) -> None:
        url = _build_url("/configuration/languages", "secret")
        assert "page=" not in url
        assert "api_key=secret" in url


class TestGetRows:
    def test_paginates_until_total_pages_and_saves_state(self) -> None:
        responses = [
            _make_response(200, {"page": 1, "results": [{"id": 1}], "total_pages": 2}),
            _make_response(200, {"page": 2, "results": [{"id": 2}], "total_pages": 2}),
        ]
        manager = _make_manager()
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=_fake_session(responses)):
            batches = list(get_rows("k", "movie_popular", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}]]
        # State saved after the first page only (the last page has nothing more to resume to).
        manager.save_state.assert_called_once_with(TMDbResumeConfig(next_page=2))

    def test_resumes_from_saved_page(self) -> None:
        responses = [_make_response(200, {"page": 5, "results": [{"id": 5}], "total_pages": 5})]
        manager = _make_manager(resume=TMDbResumeConfig(next_page=5))
        session = _fake_session(responses)
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=session):
            batches = list(get_rows("k", "movie_popular", mock.MagicMock(), manager))

        assert batches == [[{"id": 5}]]
        # Picks up at page 5, not page 1.
        assert "page=5" in session.get.call_args_list[0].args[0]
        manager.save_state.assert_not_called()

    def test_non_paginated_endpoint_yields_single_batch(self) -> None:
        responses = [_make_response(200, {"genres": [{"id": 28, "name": "Action"}]})]
        manager = _make_manager()
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=_fake_session(responses)):
            batches = list(get_rows("k", "movie_genres", mock.MagicMock(), manager))

        assert batches == [[{"id": 28, "name": "Action"}]]
        manager.save_state.assert_not_called()

    def test_empty_results_first_page_yields_nothing(self) -> None:
        responses = [_make_response(200, {"page": 1, "results": [], "total_pages": 0})]
        manager = _make_manager()
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=_fake_session(responses)):
            batches = list(get_rows("k", "movie_popular", mock.MagicMock(), manager))

        assert batches == []

    def test_stops_at_max_pages(self) -> None:
        # total_pages larger than the cap: page count must be bounded by MAX_PAGES, not total_pages.
        responses = [
            _make_response(200, {"page": p, "results": [{"id": p}], "total_pages": 10_000})
            for p in range(1, tmdb_module.MAX_PAGES + 1)
        ]
        manager = _make_manager()
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=_fake_session(responses)):
            batches = list(get_rows("k", "movie_popular", mock.MagicMock(), manager))

        assert len(batches) == tmdb_module.MAX_PAGES


class TestRetry:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = _fake_session([_make_response(status, {})])
        # Call the undecorated fetch directly to assert the classification without backoff sleeps.
        with pytest.raises(tmdb_module.TMDbRetryableError):
            tmdb_module._do_fetch(session, "https://api.themoviedb.org/3/x", mock.MagicMock())

    def test_client_error_raises_for_status(self) -> None:
        session = _fake_session([_make_response(404, {})])
        with pytest.raises(requests.HTTPError):
            tmdb_module._do_fetch(session, "https://api.themoviedb.org/3/x", mock.MagicMock())

    def test_error_message_scrubs_api_key_from_url(self) -> None:
        # The api_key rides in the query string; a 4xx must not leak it into the propagated error.
        response = _make_response(401, {"status_code": 7})
        response.url = "https://api.themoviedb.org/3/configuration?api_key=supersecret&page=1"
        session = _fake_session([response])
        with pytest.raises(requests.HTTPError) as exc:
            tmdb_module._do_fetch(session, "x", mock.MagicMock())
        message = str(exc.value)
        assert "supersecret" not in message
        # Base host/path is preserved so get_non_retryable_errors() can still match on it.
        assert "https://api.themoviedb.org/3/configuration" in message


class TestValidateCredentials:
    def test_valid_key_returns_no_message(self) -> None:
        session = _fake_session([_make_response(200, {})])
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=session):
            assert validate_credentials("k") == (True, None)

    def test_401_reports_invalid_key(self) -> None:
        session = _fake_session([_make_response(401, {})])
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message == "Invalid TMDB API key"

    @pytest.mark.parametrize("status", [404, 429, 500, 503])
    def test_non_401_failure_does_not_claim_invalid_key(self, status: int) -> None:
        # A transient/service-side failure must not be reported as an invalid credential.
        session = _fake_session([_make_response(status, {})])
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message is not None
        assert message != "Invalid TMDB API key"

    def test_network_error_does_not_claim_invalid_key(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(tmdb_module, "make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message is not None
        assert message != "Invalid TMDB API key"


class TestTMDbSource:
    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("movie_popular", ["id"]),
            ("languages", ["iso_639_1"]),
            ("countries", ["iso_3166_1"]),
        ],
    )
    def test_source_response_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = tmdb_source("k", endpoint, mock.MagicMock(), _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
