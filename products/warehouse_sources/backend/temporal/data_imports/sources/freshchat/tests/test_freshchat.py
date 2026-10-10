import json
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import urlsplit

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat import (
    FreshchatHostNotAllowedError,
    FreshchatResumeConfig,
    freshchat_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.settings import (
    PER_PAGE,
    USERS_CREATED_FROM,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the freshchat module.
FRESHCHAT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat.make_tracked_session"
)

BASE_HOST = "acme.freshchat.com"

# What a Freshworks portal domain answers with on these paths: the web app, not the API.
HTML_BODY = b"<!DOCTYPE html><html><head><title>Freshworks</title></head><body></body></html>"


def _page(data_key: str, items: list[dict], current: int, total_pages: int) -> Response:
    body = {
        data_key: items,
        "pagination": {"current_page": current, "total_pages": total_pages, "total_items": 999},
    }
    return _resp(body)


def _raw_resp(content: bytes, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = content
    return resp


def _resp(body: Any, status: int = 200, headers: Optional[dict] = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode() if body is not None else b""
    if headers:
        resp.headers.update(headers)
    return resp


def _make_manager(resume_state: Optional[FreshchatResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared. The prepared request's URL is pinned to the (allowed) base host so the
    client's SSRF host check passes.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = f"https://{BASE_HOST}/v2/resource"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _wire_routed(
    session: mock.MagicMock, handler: Callable[[str, dict[str, Any]], Response]
) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session whose response is chosen by the request path.

    Fan-out interleaves parent and child requests, so a fixed response list cannot express
    "this path answers with that page". Returns the (path, params) log in call order.
    """
    session.headers = {}
    calls: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared.fc_call = (urlsplit(request.url).path, dict(request.params or {}))
        calls.append(prepared.fc_call)
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = lambda prepared, **kwargs: handler(*prepared.fc_call)
    return calls


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_page_number_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page("agents", [{"id": 1}], current=1, total_pages=2),
                _page("agents", [{"id": 2}], current=2, total_pages=2),
            ],
        )
        manager = _make_manager()

        rows = _rows(
            freshchat_source("key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert rows == [{"id": 1}, {"id": 2}]
        # The API reports total_pages=2, so it stops right after page 2 — no extra empty request.
        assert session.send.call_count == 2
        assert params[0]["page"] == 1
        assert params[0]["items_per_page"] == str(PER_PAGE)
        assert params[1]["page"] == 2
        # State saved once, pointing at page 2 (the next page after the first was written).
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FreshchatResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_is_redacted_from_samples(self, MockSession) -> None:
        # The token rides in the Authorization header; it must be value-redacted from captured
        # HTTP samples via the tracked session's redact_values.
        session = MockSession.return_value
        _wire(session, [_page("agents", [{"id": 1}], current=1, total_pages=1)])

        _rows(
            freshchat_source(
                "secret-key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert "secret-key" in MockSession.call_args.kwargs.get("redact_values", ())

    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_resp({"error": "boom"}, status=status_code)])

        with pytest.raises(requests.HTTPError):
            _rows(
                freshchat_source(
                    "key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
                )
            )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_html_body_raises_the_mapped_non_retryable_error(self, MockSession) -> None:
        # A domain that serves the web app answers 200 with HTML. That must fail the table once with
        # the message the source maps, not retry a body that can never parse.
        session = MockSession.return_value
        _wire(session, [_raw_resp(HTML_BODY)])

        with pytest.raises(RESTClientNonRetryableError) as exc:
            _rows(
                freshchat_source(
                    "key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
                )
            )

        assert str(exc.value).startswith("Non-JSON response from")
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_disallowed_host_raises_before_any_request(self, MockSession) -> None:
        # A saved-then-edited domain must never receive the stored token at sync time (SSRF).
        session = MockSession.return_value
        _wire(session, [])

        with pytest.raises(FreshchatHostNotAllowedError):
            _rows(
                freshchat_source(
                    "key",
                    "metadata.google.internal",
                    "agents",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                )
            )

        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_response_raises_and_is_not_followed(self, MockSession) -> None:
        # A 3xx from the allowed host could point anywhere; following it would defeat the host
        # allowlist, so it must surface as a hard error instead.
        session = MockSession.return_value
        _wire(session, [_resp(None, status=302, headers={"Location": "http://169.254.169.254/"})])

        with pytest.raises(ValueError):
            _rows(
                freshchat_source(
                    "key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
                )
            )

        assert session.send.call_args.kwargs.get("allow_redirects") is False


class TestFanout:
    """Freshchat exposes no top-level conversations list, so both conversation tables are reached
    by fanning out from Users."""

    @staticmethod
    def _call(endpoint: str, session: mock.MagicMock) -> list[dict[str, Any]]:
        return _rows(
            freshchat_source(
                "key", BASE_HOST, endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_user_conversations_carries_the_parent_user_id(self, MockSession) -> None:
        session = MockSession.return_value
        pages = {
            "/v2/users": _page("users", [{"id": "u1"}, {"id": "u2"}], current=1, total_pages=1),
            "/v2/users/u1/conversations": _resp({"conversations": [{"id": "c1"}]}),
            "/v2/users/u2/conversations": _resp({"conversations": [{"id": "c2"}, {"id": "c3"}]}),
        }
        calls = _wire_routed(session, lambda path, params: pages[path])

        rows = self._call("user_conversations", session)

        # A conversation can be listed under more than one user, so the row has to name its parent
        # — the primary key is (user_id, id).
        assert rows == [
            {"id": "c1", "user_id": "u1"},
            {"id": "c2", "user_id": "u2"},
            {"id": "c3", "user_id": "u2"},
        ]
        assert calls[0][1]["created_from"] == USERS_CREATED_FROM
        # The child endpoint documents no query params; sending page-size or sort params there
        # would be undocumented guesswork.
        assert calls[1][1] == {}

    def test_conversation_messages_is_not_resumable(self) -> None:
        response = freshchat_source(
            "key",
            BASE_HOST,
            "conversation_messages",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(FreshchatResumeConfig(page=2)),
        )

        assert response.supports_resume is False


class TestValidateCredentials:
    # A Freshworks portal domain answers the probe with its web app, not the API. An empty body and
    # a truncated body stay acceptable, because the sync path reads an empty 2xx as an empty page
    # and retries a truncated one, rather than calling either a broken host.
    @pytest.mark.parametrize(
        "body, returned_json",
        [(HTML_BODY, False), (b"", True), (b'{"configuration": {"app_id"', True)],
    )
    def test_probe_reports_whether_the_body_is_json(self, body: bytes, returned_json: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = _raw_resp(body)

        with mock.patch(FRESHCHAT_SESSION_PATCH, return_value=session):
            assert validate_credentials(BASE_HOST, "key") == (200, returned_json)

    def test_connection_error_returns_none(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("nope")

        with mock.patch(FRESHCHAT_SESSION_PATCH, return_value=session):
            assert validate_credentials(BASE_HOST, "key") == (None, False)

    def test_session_redacts_api_key_from_samples(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _resp(None, status=200)

        with mock.patch(FRESHCHAT_SESSION_PATCH, return_value=session) as mock_make:
            validate_credentials(BASE_HOST, "secret-key")

        assert mock_make.call_args.kwargs.get("redact_values") == ("secret-key",)

    def test_probe_disables_redirects_to_protect_token(self) -> None:
        # The token rides on the probe; the session must be built with redirects pinned off so a
        # redirect can't replay it to the redirect target during validation.
        session = mock.MagicMock()
        session.get.return_value = _resp(None, status=200)

        with mock.patch(FRESHCHAT_SESSION_PATCH, return_value=session) as mock_make:
            validate_credentials(BASE_HOST, "key")

        assert mock_make.call_args.kwargs.get("allow_redirects") is False
