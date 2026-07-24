import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb import tmdb as tmdb_module
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.tmdb import (
    TMDbResumeConfig,
    tmdb_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the tmdb module.
TMDB_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.tmdb.make_tracked_session"


def _page_response(rows: list[dict[str, Any]], *, page: int, total_pages: int) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.url = "https://api.themoviedb.org/3/movie/popular"
    resp._content = json.dumps({"page": page, "results": rows, "total_pages": total_pages}).encode()
    return resp


def _body_response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.url = "https://api.themoviedb.org/3/x"
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status_code: int, url: str) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = "Unauthorized" if status_code == 401 else "Error"
    resp.url = url
    resp._content = json.dumps({"status_code": 7}).encode()
    return resp


def _make_manager(resume: TMDbResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, api_key: str = "k"):
    return tmdb_source(api_key, endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_pages_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page_response([{"id": 1}], page=1, total_pages=2),
                _page_response([{"id": 2}], page=2, total_pages=2),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("movie_popular", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert params[0]["page"] == 1
        assert params[0]["language"] == "en-US"
        assert params[1]["page"] == 2
        # State saved after the first page only (the last page has nothing more to resume to).
        manager.save_state.assert_called_once_with(TMDbResumeConfig(next_page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page_response([{"id": 5}], page=5, total_pages=5)])
        manager = _make_manager(resume=TMDbResumeConfig(next_page=5))

        rows = _rows(_source("movie_popular", manager))

        assert rows == [{"id": 5}]
        # Picks up at page 5, not page 1, and never checkpoints again.
        assert params[0]["page"] == 5
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page_response([], page=1, total_pages=0)])
        manager = _make_manager()

        assert _rows(_source("movie_popular", manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_max_pages(self, MockSession) -> None:
        # total_pages far above the cap: request count must be bounded by MAX_PAGES, not total_pages.
        session = MockSession.return_value
        _wire(
            session,
            [_page_response([{"id": p}], page=p, total_pages=10_000) for p in range(1, tmdb_module.MAX_PAGES + 1)],
        )
        manager = _make_manager()

        rows = _rows(_source("movie_popular", manager))

        assert len(rows) == tmdb_module.MAX_PAGES
        assert session.send.call_count == tmdb_module.MAX_PAGES


class TestNonPaginatedEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_genres_endpoint_extracts_from_key_and_makes_one_request(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_body_response({"genres": [{"id": 28, "name": "Action"}]})])
        manager = _make_manager()

        rows = _rows(_source("movie_genres", manager))

        assert rows == [{"id": 28, "name": "Action"}]
        assert session.send.call_count == 1
        # Reference endpoints omit the language param entirely (parity with the old URL builder).
        assert "language" not in params[0]
        assert "page" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bare_list_endpoint_yields_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_body_response([{"iso_639_1": "en", "name": "English"}])])
        manager = _make_manager()

        rows = _rows(_source("languages", manager))

        assert rows == [{"iso_639_1": "en", "name": "English"}]
        manager.save_state.assert_not_called()


class TestErrorRedaction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_401_scrubs_api_key_but_preserves_host(self, MockSession) -> None:
        # The api_key rides in the query string; a 4xx must not leak it into the propagated error,
        # while the base host stays intact so get_non_retryable_errors() can still match on it.
        session = MockSession.return_value
        _wire(
            session,
            [_error_response(401, "https://api.themoviedb.org/3/movie/popular?api_key=supersecret&page=1")],
        )
        manager = _make_manager()

        with pytest.raises(requests.HTTPError) as exc:
            _rows(_source("movie_popular", manager, api_key="supersecret"))

        message = str(exc.value)
        assert "supersecret" not in message
        assert "https://api.themoviedb.org/3/movie/popular" in message


class TestValidateCredentials:
    @mock.patch(TMDB_SESSION_PATCH)
    def test_valid_key_returns_no_message(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("k") == (True, None)

    @mock.patch(TMDB_SESSION_PATCH)
    def test_401_reports_invalid_key(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("k") == (False, "Invalid TMDB API key")

    @pytest.mark.parametrize("status", [404, 429, 500, 503])
    @mock.patch(TMDB_SESSION_PATCH)
    def test_non_401_failure_does_not_claim_invalid_key(self, mock_session, status: int) -> None:
        # A transient/service-side failure must not be reported as an invalid credential.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message is not None
        assert message != "Invalid TMDB API key"

    @mock.patch(TMDB_SESSION_PATCH)
    def test_network_error_does_not_claim_invalid_key(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message is not None
        assert message != "Invalid TMDB API key"


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("movie_popular", ["id"]),
            ("languages", ["iso_639_1"]),
            ("countries", ["iso_3166_1"]),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys(self, MockSession, endpoint: str, expected_keys: list[str]) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_count == 1
        assert response.partition_size == 1
