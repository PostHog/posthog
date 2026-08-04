import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.mailosaur import (
    MailosaurResumeConfig,
    _format_received_after,
    mailosaur_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the mailosaur module.
MAILOSAUR_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.mailosaur.make_tracked_session"
)

Handler = Callable[[str, dict[str, Any]], Response]


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, handler: Handler) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session so each request is served by ``handler(url, params)``.

    Returns a list capturing every prepared request's (url, params) AT SEND TIME — ``request.params``
    is a single dict mutated in place across pages, so a copy is snapshotted per request.
    """
    session.headers = {}
    captured: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        params = dict(request.params or {})
        captured.append((request.url, params))
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared._request = request
        return prepared

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        request = prepared._request
        return handler(request.url, dict(request.params or {}))

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return captured


def _make_manager(resume_state: MailosaurResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _server_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["server"][0]


def _message_requests(captured: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    return [(url, params) for url, params in captured if "/api/messages" in url]


def _servers_fetched(captured: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Servers the run actually paginated, in order (keyed off the first page request per server)."""
    return [_server_of(url) for url, params in _message_requests(captured) if params.get("page") == 0]


class TestFormatReceivedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("none", None, None),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_received_after(value) == expected

    @parameterized.expand([("int_epoch", 1234567890), ("string", "not-a-date")])
    def test_unexpected_type_raises(self, _name: str, value: Any) -> None:
        # The messages cursor is a DateTime; an int/str would produce a receivedAfter Mailosaur
        # silently ignores (a full re-fetch), so we fail loud instead.
        with pytest.raises(TypeError):
            _format_received_after(value)


class TestMessagesFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_injects_server_and_fans_out_over_servers(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str, params: dict[str, Any]) -> Response:
            if "/api/servers" in url:
                return _response({"items": [{"id": "s1"}, {"id": "s2"}]})
            server = _server_of(url)
            if params["page"] == 0:
                return _response({"items": [{"id": f"m-{server}"}]})
            return _response({"items": []})

        _wire(session, handler)
        rows = _rows(
            mailosaur_source("key", "messages", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        # Every message row must carry its parent server id — that's half of the (server, id)
        # primary key, and the summary payload omits it.
        assert rows == [
            {"id": "m-s1", "server": "s1"},
            {"id": "m-s2", "server": "s2"},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_empty_page_and_checkpoints_progress(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str, params: dict[str, Any]) -> Response:
            if "/api/servers" in url:
                return _response({"items": [{"id": "s1"}]})
            page = params["page"]
            if page == 0:
                return _response({"items": [{"id": "a"}, {"id": "b"}]})
            if page == 1:
                return _response({"items": [{"id": "c"}]})
            return _response({"items": []})

        captured = _wire(session, handler)
        manager = _make_manager()
        rows = _rows(mailosaur_source("key", "messages", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["a", "b", "c"]
        # Page param progresses 0 -> 1 -> 2 (the empty page that terminates the server).
        assert [params["page"] for _url, params in _message_requests(captured)] == [0, 1, 2]
        # State is checkpointed AFTER yielding a page, bookmarking the next page to fetch, so a crash
        # re-yields rather than skips (merge dedupes on the primary key).
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert any(s.paginator_state is not None and s.paginator_state.get("child_state") == {"page": 1} for s in saved)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_fanout_state(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str, params: dict[str, Any]) -> Response:
            if "/api/servers" in url:
                return _response({"items": [{"id": "s1"}, {"id": "s2"}]})
            if params["page"] == 0:
                return _response({"items": [{"id": f"m-{_server_of(url)}"}]})
            return _response({"items": []})

        captured = _wire(session, handler)
        # s1 already fully synced (its child path is in `completed`), so the resumed run must skip it.
        resume = MailosaurResumeConfig(
            paginator_state={"completed": ["/api/messages?server=s1"], "current": None, "child_state": None}
        )
        rows = _rows(
            mailosaur_source("key", "messages", team_id=1, job_id="j", resumable_source_manager=_make_manager(resume))
        )

        assert _servers_fetched(captured) == ["s2"]
        assert rows == [{"id": "m-s2", "server": "s2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_resume_state_starts_fresh(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str, params: dict[str, Any]) -> Response:
            if "/api/servers" in url:
                return _response({"items": [{"id": "s1"}, {"id": "s2"}]})
            if params["page"] == 0:
                return _response({"items": [{"id": f"m-{_server_of(url)}"}]})
            return _response({"items": []})

        captured = _wire(session, handler)
        # Old-shape state (server_id/page, no paginator_state) must still deserialize and simply
        # restart the fan-out — a re-fetch the merge dedupes.
        resume = MailosaurResumeConfig(server_id="s2", page=0)
        rows = _rows(
            mailosaur_source("key", "messages", team_id=1, job_id="j", resumable_source_manager=_make_manager(resume))
        )

        assert _servers_fetched(captured) == ["s1", "s2"]
        assert rows == [{"id": "m-s1", "server": "s1"}, {"id": "m-s2", "server": "s2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_passes_received_after(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str, _params: dict[str, Any]) -> Response:
            if "/api/servers" in url:
                return _response({"items": [{"id": "s1"}]})
            return _response({"items": []})

        captured = _wire(session, handler)
        _rows(
            mailosaur_source(
                "key",
                "messages",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )
        message_params = [params for _url, params in _message_requests(captured)]
        assert message_params
        assert all(p.get("receivedAfter") == "2026-01-02T03:04:05Z" for p in message_params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_received_after_on_full_refresh(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str, _params: dict[str, Any]) -> Response:
            if "/api/servers" in url:
                return _response({"items": [{"id": "s1"}]})
            return _response({"items": []})

        captured = _wire(session, handler)
        _rows(mailosaur_source("key", "messages", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert all("receivedAfter" not in params for _url, params in _message_requests(captured))


class TestSimpleEndpoints:
    @parameterized.expand([("servers", "/api/servers"), ("usage_transactions", "/api/usage/transactions")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_request_yields_items(self, endpoint: str, expected_path: str, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str, _params: dict[str, Any]) -> Response:
            assert expected_path in url
            return _response({"items": [{"id": "x"}]})

        captured = _wire(session, handler)
        rows = _rows(mailosaur_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert rows == [{"id": "x"}]
        # A single-request full-refresh endpoint issues exactly one call.
        assert len(captured) == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Mailosaur API key"),
            ("forbidden", 403, False, "This Mailosaur API key cannot list servers. Use an account-level API key."),
            ("server_error", 500, False, "Mailosaur API error: 500"),
        ]
    )
    @mock.patch(MAILOSAUR_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status_code: int, expected_ok: bool, expected_error: str | None, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        ok, error = validate_credentials("key")
        assert ok is expected_ok
        assert error == expected_error

    @mock.patch(MAILOSAUR_SESSION_PATCH)
    def test_transport_error_is_not_validated(self, mock_session) -> None:
        # A credential probe must never raise out of validate_credentials; a transport error just
        # means "not validated".
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, error = validate_credentials("key")
        assert ok is False
        assert error is not None


class TestMailosaurSourceResponse:
    @parameterized.expand(
        [
            ("messages", ["server", "id"], "desc", ["received"]),
            ("servers", ["id"], "asc", None),
            ("usage_transactions", ["timestamp"], "asc", None),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_keys: list[str] | None
    ) -> None:
        response = mailosaur_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # sort_mode must match the real arrival order — messages come newest-first (desc), and a
        # wrong value corrupts the incremental watermark checkpoint.
        assert response.sort_mode == sort_mode
        assert response.partition_keys == partition_keys
