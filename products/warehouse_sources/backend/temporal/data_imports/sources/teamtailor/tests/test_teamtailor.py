import json
from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor import teamtailor
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.settings import (
    ENDPOINTS,
    TEAMTAILOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.teamtailor import (
    API_VERSION,
    PAGE_SIZE,
    TeamtailorResumeConfig,
    check_access,
    teamtailor_source,
    validate_credentials,
)

# The RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _page(rows: list[dict], next_url: str | None = None, status: int = 200) -> Response:
    body: dict[str, Any] = {"data": rows, "links": {"next": next_url} if next_url else {}, "meta": {}}
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _raw(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: TeamtailorResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(mock_make_session: MagicMock, responses: list[Any]) -> tuple[requests.Session, list[str]]:
    """Route the RESTClient's session through a real ``requests.Session`` so ``prepared.url`` is a
    genuine URL, while ``send`` returns each fixture in order. A fixture that is an ``Exception`` is
    raised. Returns the session and the list of URLs sent, in order."""
    session = requests.Session()
    sent: list[str] = []
    queue = list(responses)

    def _send(prepared: Any, **kwargs: Any) -> Response:
        sent.append(prepared.url)
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(result, Exception):
            raise result
        return result

    cast(Any, session).send = mock.MagicMock(side_effect=_send)
    mock_make_session.return_value = session
    return session, sent


def _rows(endpoint: str, manager: MagicMock) -> list[dict[str, Any]]:
    response = teamtailor_source("tt-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


class TestPagination:
    @patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_and_stops(self, mock_make_session: MagicMock) -> None:
        _wire(mock_make_session, [_page([{"id": "1"}, {"id": "2"}], next_url=None)])
        manager = _make_manager()
        rows = _rows("candidates", manager)

        assert rows == [{"id": "1"}, {"id": "2"}]
        # No `next` link, so nothing is persisted.
        manager.save_state.assert_not_called()

    @patch(CLIENT_SESSION_PATCH)
    def test_first_page_sends_page_size_param(self, mock_make_session: MagicMock) -> None:
        _, sent = _wire(mock_make_session, [_page([{"id": "1"}], next_url=None)])
        _rows("jobs", _make_manager())

        assert sent[0].startswith("https://api.teamtailor.com/v1/jobs")
        assert parse_qs(urlsplit(sent[0]).query) == {"page[size]": [str(PAGE_SIZE)]}

    @patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_verbatim_until_null(self, mock_make_session: MagicMock) -> None:
        next_url = "https://api.teamtailor.com/v1/candidates?page%5Bnumber%5D=2"
        _, sent = _wire(
            mock_make_session,
            [_page([{"id": "1"}], next_url=next_url), _page([{"id": "2"}], next_url=None)],
        )
        manager = _make_manager()
        rows = _rows("candidates", manager)

        assert rows == [{"id": "1"}, {"id": "2"}]
        # First request carries the page[size] param; the second follows the `next` URL verbatim,
        # with no first-page params re-appended.
        assert sent[0].startswith("https://api.teamtailor.com/v1/candidates?page%5Bsize%5D=30")
        assert sent[1] == next_url
        # Saved after page 1 (a next page remains), never after the final page.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [TeamtailorResumeConfig(next_url=next_url)]

    @patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, mock_make_session: MagicMock) -> None:
        resume_url = "https://api.teamtailor.com/v1/candidates?page%5Bnumber%5D=3"
        _, sent = _wire(mock_make_session, [_page([{"id": "9"}], next_url=None)])
        manager = _make_manager(TeamtailorResumeConfig(next_url=resume_url))
        rows = _rows("candidates", manager)

        assert rows == [{"id": "9"}]
        # The first fetch follows the saved cursor, never re-requesting the first page.
        assert sent == [resume_url]

    @patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, mock_make_session: MagicMock) -> None:
        _wire(mock_make_session, [_page([], next_url=None)])
        manager = _make_manager()
        rows = _rows("candidates", manager)

        assert rows == []
        manager.save_state.assert_not_called()


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @patch("tenacity.nap.time.sleep")
    @patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_reraised(
        self, _name: str, status: int, mock_make_session: MagicMock, _sleep: MagicMock
    ) -> None:
        session, _ = _wire(mock_make_session, [_raw({"errors": []}, status=status)])
        with pytest.raises(RESTClientRetryableError):
            _rows("candidates", _make_manager())
        # The client retries transient statuses up to its default attempt cap before giving up.
        assert cast("MagicMock", session.send).call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @patch("tenacity.nap.time.sleep")
    @patch(CLIENT_SESSION_PATCH)
    def test_client_errors_fail_permanently_without_retry(
        self, _name: str, status: int, mock_make_session: MagicMock, _sleep: MagicMock
    ) -> None:
        session, _ = _wire(mock_make_session, [_raw({"errors": []}, status=status)])
        with pytest.raises(requests.HTTPError):
            _rows("candidates", _make_manager())
        # Auth/not-found failures are permanent — the request is issued exactly once.
        assert cast("MagicMock", session.send).call_count == 1

    @patch("tenacity.nap.time.sleep")
    @patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retried(self, mock_make_session: MagicMock, _sleep: MagicMock) -> None:
        # JSON:API always wraps rows under `data`; a bare-array (or otherwise misshapen) 200 body is
        # treated as a transient malformed payload and retried rather than ingested as rows.
        session, _ = _wire(mock_make_session, [_raw([{"id": "1"}], status=200)])
        with pytest.raises(RESTClientRetryableError):
            _rows("candidates", _make_manager())
        assert cast("MagicMock", session.send).call_count == 5


class TestAuthHeaders:
    def test_headers_carry_token_and_api_version(self) -> None:
        headers = teamtailor._headers("tt-key")
        assert headers["Authorization"] == "Token token=tt-key"
        assert headers["X-Api-Version"] == API_VERSION
        assert headers["Accept"] == "application/vnd.api+json"

    def test_version_headers_carry_no_secret(self) -> None:
        # The API key travels via the framework auth config, not these static headers.
        headers = teamtailor._version_headers()
        assert "Authorization" not in headers
        assert headers["X-Api-Version"] == API_VERSION

    @patch(CLIENT_SESSION_PATCH)
    def test_token_auth_header_is_sent(self, mock_make_session: MagicMock) -> None:
        session, _ = _wire(mock_make_session, [_page([{"id": "1"}], next_url=None)])
        captured: dict[str, str] = {}

        original_prepare = session.prepare_request

        def _prepare(request: Any) -> Any:
            prepared = original_prepare(request)
            captured.update(prepared.headers)
            return prepared

        cast(Any, session).prepare_request = mock.MagicMock(side_effect=_prepare)
        _rows("candidates", _make_manager())

        assert captured["Authorization"] == "Token token=tt-key"
        assert captured["X-Api-Version"] == API_VERSION


class TestCheckAccess:
    def _configure_session(self, mock_make_session: MagicMock, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        mock_make_session.return_value = session
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Teamtailor returned HTTP 500"),
        ]
    )
    @mock.patch.object(teamtailor, "make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        self._configure_session(mock_make_session, response)
        assert check_access("tt-key") == (expected_status, expected_message)

    @mock.patch.object(teamtailor, "make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_make_session: MagicMock) -> None:
        self._configure_session(mock_make_session, requests.ConnectionError("boom"))
        status, message = check_access("tt-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Teamtailor API key"),
            ("forbidden", 403, False, "Invalid Teamtailor API key"),
            ("server_error", 500, False, "Teamtailor returned HTTP 500"),
        ]
    )
    @mock.patch.object(teamtailor, "make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        self._configure_session(mock_make_session, response)
        assert validate_credentials("tt-key") == (expected_valid, expected_message)


class TestTeamtailorSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = teamtailor_source(
            "tt-key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in TEAMTAILOR_ENDPOINTS.values())
        assert set(TEAMTAILOR_ENDPOINTS) == set(ENDPOINTS)
