import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.persistiq import (
    PersistiqResumeConfig,
    persistiq_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the persistiq module.
PERSISTIQ_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.persistiq.make_tracked_session"
)

_URL = "https://api.persistiq.com/v1/leads?page=1"


def _response(body: Any, status: int = 200, reason: str = "", url: str = _URL) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = url
    resp._content = json.dumps(body).encode()
    return resp


def _page(items: list[dict[str, Any]], has_more: bool, list_key: str = "leads") -> Response:
    return _response({list_key: items, "has_more": has_more, "next_page": None})


def _make_manager(resume_state: PersistiqResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, api_key: str = "pq-key") -> Any:
    return persistiq_source(api_key=api_key, endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_items_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": "l_1"}, {"id": "l_2"}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source("leads", manager))

        assert rows == [{"id": "l_1"}, {"id": "l_2"}]
        assert params[0]["page"] == 1
        assert session.send.call_count == 1
        # No further pages, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_has_more_is_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"id": "l_1"}], has_more=True),
                _page([{"id": "l_2"}], has_more=True),
                # The final page carries rows AND has_more=False — termination reads the flag, not
                # an empty page, so no extra request is made past it.
                _page([{"id": "l_3"}], has_more=False),
            ],
        )

        rows = _rows(_source("leads", _make_manager()))

        assert [r["id"] for r in rows] == ["l_1", "l_2", "l_3"]
        assert [p["page"] for p in params] == [1, 2, 3]
        assert session.send.call_count == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_batch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": "l_1"}], has_more=True), _page([{"id": "l_2"}], has_more=False)])

        manager = _make_manager()
        _rows(_source("leads", manager))

        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        assert [call.args[0].next_page for call in manager.save_state.call_args_list] == [2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [_page([{"id": "l_2"}], has_more=True), _page([{"id": "l_3"}], has_more=False)],
        )

        manager = _make_manager(PersistiqResumeConfig(next_page=2))
        rows = _rows(_source("leads", manager))

        assert [r["id"] for r in rows] == ["l_2", "l_3"]
        # Page 1 must never be fetched on resume.
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source("leads", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_endpoint_specific_list_key(self, MockSession) -> None:
        # `users` reads rows from the "users" envelope key, not "leads".
        session = MockSession.return_value
        _wire(session, [_page([{"id": "u_1"}], has_more=False, list_key="users")])

        rows = _rows(_source("users", _make_manager()))

        assert rows == [{"id": "u_1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_registers_api_key_for_redaction(self, MockSession) -> None:
        # The api key rides in the `x-api-key` header through the tracked transport; it must be
        # registered for redaction so it never lands in HTTP logs, samples, or error messages.
        session = MockSession.return_value
        _wire(session, [_page([], has_more=False)])

        _rows(_source("leads", _make_manager(), api_key="secret"))

        MockSession.assert_called_once_with(redact_values=("secret",))


class TestMalformedBody:
    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_list_key_is_retried_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"has_more": False}), _page([{"id": "l_1"}], has_more=False)])

        rows = _rows(_source("leads", _make_manager()))

        assert rows == [{"id": "l_1"}]
        assert session.send.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_dict_body_is_retried_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "l_1"}]), _page([{"id": "l_1"}], has_more=False)])

        rows = _rows(_source("leads", _make_manager()))

        assert rows == [{"id": "l_1"}]
        assert session.send.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_persistently_malformed_body_exhausts_and_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"has_more": False})] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("leads", _make_manager()))
        assert session.send.call_count == 5


class TestRetries:
    @pytest.mark.parametrize("status", [429, 500, 503])
    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, MockSession, _sleep, status: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status), _page([{"id": "l_1"}], has_more=False)])

        rows = _rows(_source("leads", _make_manager()))

        assert [r["id"] for r in rows] == ["l_1"]
        assert session.send.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_exhaust_then_raise(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=500)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("leads", _make_manager()))
        assert session.send.call_count == 5

    @pytest.mark.parametrize(
        ("status", "reason"),
        [(401, "Unauthorized"), (403, "Forbidden"), (404, "Not Found")],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error_without_retry(self, MockSession, status: int, reason: str) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError, match=f"{status} Client Error"):
            _rows(_source("leads", _make_manager()))
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unauthorized_message_matches_non_retryable_mapping(self, MockSession) -> None:
        # source.py maps this exact substring to the friendly invalid-key message.
        session = MockSession.return_value
        _wire(session, [_response({}, status=401, reason="Unauthorized")])

        with pytest.raises(
            requests.HTTPError, match="401 Client Error: Unauthorized for url: https://api.persistiq.com/v1"
        ):
            _rows(_source("leads", _make_manager()))


class TestValidateCredentials:
    def _validate(self, status: int | None = None, raises: Exception | None = None) -> tuple[bool, str | None]:
        with mock.patch(PERSISTIQ_SESSION_PATCH) as MockSession:
            get = MockSession.return_value.get
            if raises is not None:
                get.side_effect = raises
            else:
                get.return_value = mock.MagicMock(status_code=status)
            return validate_credentials("pq-key")

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (200, (True, None)),
            (401, (False, "Invalid PersistIQ API key")),
            (403, (False, "Invalid PersistIQ API key")),
            (500, (False, "PersistIQ returned HTTP 500")),
        ],
    )
    def test_status_mapping(self, status: int, expected: tuple[bool, str | None]) -> None:
        assert self._validate(status=status) == expected

    def test_connection_error_is_invalid(self) -> None:
        valid, message = self._validate(raises=requests.ConnectionError("boom"))
        assert valid is False
        assert message is not None
