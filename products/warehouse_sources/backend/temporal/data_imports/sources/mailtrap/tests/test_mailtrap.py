import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.mailtrap import (
    MAILTRAP_BASE_URL,
    MailtrapResumeConfig,
    mailtrap_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.settings import (
    ENDPOINTS,
    MAILTRAP_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the mailtrap module.
MAILTRAP_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.mailtrap.make_tracked_session"
)


def _response(body: Any, *, status: int = 200, url: str = f"{MAILTRAP_BASE_URL}/api/x") -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = "Error"
    resp._content = json.dumps(body).encode() if body is not None else b""
    return resp


def _make_manager(resume_state: MailtrapResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy is snapshotted when
    each request is prepared rather than after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _wire_repeat(session: mock.MagicMock, body: Any, *, status: int = 200) -> None:
    """Wire a mock session to return the same response for every (retried) request."""
    session.headers = {}
    session.prepare_request.side_effect = lambda request: mock.MagicMock()
    session.send.side_effect = lambda *args, **kwargs: _response(body, status=status)


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return mailtrap_source(
        api_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_email_logs_follows_next_page_cursor_until_null(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"messages": [{"message_id": "m1"}], "next_page_cursor": "c2"}),
                _response({"messages": [{"message_id": "m2"}], "next_page_cursor": None}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("email_logs", manager))

        assert rows == [{"message_id": "m1"}, {"message_id": "m2"}]
        # The cursor param only rides the second request; the first page must not carry one.
        assert "search_after" not in params[0]
        assert params[1]["search_after"] == "c2"
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        manager.save_state.assert_called_once_with(MailtrapResumeConfig(cursor="c2"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_email_logs_incremental_sends_sent_after_on_every_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"messages": [{"message_id": "m1"}], "next_page_cursor": "c2"}),
                _response({"messages": [{"message_id": "m2"}], "next_page_cursor": None}),
            ],
        )

        _rows(
            _source(
                "email_logs",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01T00:00:00Z",
            )
        )
        # The server-side bound must ride along with the cursor, or later pages walk unbounded
        # through already-synced history.
        assert len(params) == 2
        assert all(p.get("filters[sent_after]") == "2026-01-01T00:00:00Z" for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_email_logs_full_refresh_sends_no_time_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"messages": [{"message_id": "m1"}], "next_page_cursor": None})])

        _rows(_source("email_logs", _make_manager()))
        assert "filters[sent_after]" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_email_logs_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"messages": [{"message_id": "m2"}], "next_page_cursor": None})])

        manager = _make_manager(MailtrapResumeConfig(cursor="c2"))
        rows = _rows(_source("email_logs", manager))

        assert rows == [{"message_id": "m2"}]
        # The first page must never be re-fetched on resume: the saved cursor rides the first request.
        assert session.send.call_count == 1
        assert params[0]["search_after"] == "c2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_suppressions_paginates_by_last_row_id_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        page_size = MAILTRAP_ENDPOINTS["suppressions"].page_size
        assert page_size is not None
        full_page = [{"id": f"s{i}"} for i in range(page_size)]
        short_page = [{"id": "last"}]
        params = _wire(session, [_response(full_page), _response(short_page)])

        manager = _make_manager()
        rows = _rows(_source("suppressions", manager))

        assert len(rows) == page_size + 1
        # The cursor advances from the last row of the full page; the short page ends the sync.
        assert "last_id" not in params[0]
        assert params[1]["last_id"] == full_page[-1]["id"]
        manager.save_state.assert_called_once_with(MailtrapResumeConfig(cursor=full_page[-1]["id"]))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_suppressions_incremental_sends_start_time(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "s1"}])])

        _rows(
            _source(
                "suppressions",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01T00:00:00Z",
            )
        )
        assert params[0]["start_time"] == "2026-01-01T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_suppressions_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "s_last"}])])

        manager = _make_manager(MailtrapResumeConfig(cursor="s99"))
        _rows(_source("suppressions", manager))
        # The saved last-row id seeds the first request so already-synced pages are skipped.
        assert params[0]["last_id"] == "s99"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_saves_no_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"messages": [], "next_page_cursor": None})])

        manager = _make_manager()
        rows = _rows(_source("email_logs", manager))
        assert rows == []
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("email_templates", [{"id": 1}]),
            ("contact_lists", [{"id": 2, "name": "list"}]),
            ("accounts", [{"id": 3, "name": "acct"}]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_bare_array_endpoints_fetch_once(self, endpoint: str, body: list[dict], MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        manager = _make_manager()
        rows = _rows(_source(endpoint, manager))
        assert rows == body
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sending_domains_unwraps_data_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": 1, "domain_name": "example.com"}]})])

        rows = _rows(_source("sending_domains", _make_manager()))
        assert rows == [{"id": 1, "domain_name": "example.com"}]


class TestRetryClassification:
    @parameterized.expand(
        [
            ("email_logs_bare_list", "email_logs", [{"message_id": "m1"}]),
            ("email_logs_missing_key", "email_logs", {"total_count": 0}),
            ("templates_wrapped", "email_templates", {"data": []}),
        ]
    )
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_is_retryable(self, _name: str, endpoint: str, body: Any, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire_repeat(session, body)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(endpoint, _make_manager()))

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire_repeat(session, {"messages": []}, status=status)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("email_logs", _make_manager()))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"}, status=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("email_logs", _make_manager()))


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        response = _source(endpoint, _make_manager())
        config = MAILTRAP_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.incremental_param:
            # The watermark must only commit once a sync completes: email_logs is documented
            # newest-first and suppressions ordering is undocumented.
            assert response.sort_mode == "desc"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.sort_mode == "asc"
            assert response.partition_mode is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_email_logs_primary_key_is_message_id(self, MockSession) -> None:
        assert MAILTRAP_ENDPOINTS["email_logs"].primary_keys == ["message_id"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Mailtrap API token"),
            ("forbidden", 403, False, "Invalid Mailtrap API token"),
            ("server_error", 500, False, "Mailtrap returned HTTP 500"),
        ]
    )
    @mock.patch(MAILTRAP_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: Optional[str], mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("token") == (expected_valid, expected_message)

    @mock.patch(MAILTRAP_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        valid, message = validate_credentials("token")
        assert valid is False
        assert message == "Could not connect to Mailtrap"
