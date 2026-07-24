import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.browser_use import (
    BROWSER_USE_BASE_URL,
    BrowserUseResumeConfig,
    browser_use_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import BROWSER_USE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)

# browser_use builds its tracked session in its own module and hands it to the REST client.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.browser_use.make_tracked_session"
)


def _response(body: dict[str, Any], status: int = 200, url: str = f"{BROWSER_USE_BASE_URL}/sessions") -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = {200: "OK", 401: "Unauthorized", 403: "Forbidden", 429: "Too Many Requests"}.get(status, "Error")
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BrowserUseResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return snapshots of each request's url/params AT PREPARE TIME.

    ``request.params`` is a dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock | None = None):
    return browser_use_source(
        "bu_test", endpoint, team_id=1, job_id="j", resumable_source_manager=manager or _make_manager()
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @parameterized.expand(
        [
            ("sessions", "sessions", "page", "page_size"),
            ("browser_sessions", "items", "pageNumber", "pageSize"),
            ("profiles", "items", "pageNumber", "pageSize"),
            ("workspaces", "items", "pageNumber", "pageSize"),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_all_pages_aggregated_and_terminates(
        self, endpoint: str, data_key: str, page_param: str, size_param: str, MockSession
    ) -> None:
        # Two full pages then a short page: guards that every page is collected, that the endpoint's
        # own page/pageSize param names are sent (the wrong name would silently return page 1
        # forever), and that a short page terminates the loop instead of paging forever.
        session = MockSession.return_value
        size = BROWSER_USE_ENDPOINTS[endpoint].page_size
        pages = [
            [{"id": f"a{i}"} for i in range(size)],
            [{"id": f"b{i}"} for i in range(size)],
            [{"id": "c0"}, {"id": "c1"}],
        ]
        params = _wire(session, [_response({data_key: page}) for page in pages])

        rows = _rows(_source(endpoint))

        assert len(rows) == size * 2 + 2
        assert [p["params"][page_param] for p in params] == [1, 2, 3]
        assert all(p["params"][size_param] == size for p in params)

    @mock.patch(SESSION_PATCH)
    def test_total_stops_before_an_empty_page(self, MockSession) -> None:
        # A full final page whose count equals `total` must not trigger one more (empty) request.
        session = MockSession.return_value
        size = BROWSER_USE_ENDPOINTS["sessions"].page_size
        full_page = [{"id": f"a{i}"} for i in range(size)]
        _wire(session, [_response({"sessions": full_page, "total": size})])

        rows = _rows(_source("sessions"))

        assert len(rows) == size
        assert session.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_missing_data_key_is_empty_page(self, MockSession) -> None:
        # The API envelopes zero rows as a missing/empty array — treat it as the end, not an error.
        session = MockSession.return_value
        _wire(session, [_response({})])

        assert _rows(_source("sessions")) == []
        assert session.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_state_saved_after_each_yield(self, MockSession) -> None:
        # Resume state must advance to the NEXT page and only be saved when more pages remain, so a
        # crash re-yields the last page rather than skipping it.
        session = MockSession.return_value
        size = BROWSER_USE_ENDPOINTS["sessions"].page_size
        pages = [[{"id": f"a{i}"} for i in range(size)], [{"id": "b0"}]]
        _wire(session, [_response({"sessions": page}) for page in pages])

        manager = _make_manager()
        _rows(_source("sessions", manager))

        # Only the first (full) page has a successor, so exactly one save advancing to page 2.
        manager.save_state.assert_called_once_with(BrowserUseResumeConfig(page=2))

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"sessions": [{"id": "p3"}]})])

        manager = _make_manager(BrowserUseResumeConfig(page=3))
        rows = _rows(_source("sessions", manager))

        assert rows == [{"id": "p3"}]
        assert [p["params"]["page"] for p in params] == [3]


class TestSessionMessagesFanOut:
    @mock.patch(SESSION_PATCH)
    def test_fans_out_over_sessions_with_cursor(self, MockSession) -> None:
        # Two sessions, one paginated via the `after` cursor; every message must be collected and
        # stamped with its parent session id. The raw child payload omits `sessionId`, so the source
        # has to inject it — the composite [sessionId, id] primary key depends on it being present.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"sessions": [{"id": "s1"}, {"id": "s2"}]}),
                _response({"messages": [{"id": "m1"}, {"id": "m2"}], "hasMore": True}),
                _response({"messages": [{"id": "m3"}], "hasMore": False}),
                _response({"messages": [{"id": "m9"}], "hasMore": False}),
            ],
        )

        rows = _rows(_source("session_messages"))

        assert [(r["id"], r["sessionId"]) for r in rows] == [("m1", "s1"), ("m2", "s1"), ("m3", "s1"), ("m9", "s2")]
        assert [p["url"] for p in params] == [
            f"{BROWSER_USE_BASE_URL}/sessions",
            f"{BROWSER_USE_BASE_URL}/sessions/s1/messages",
            f"{BROWSER_USE_BASE_URL}/sessions/s1/messages",
            f"{BROWSER_USE_BASE_URL}/sessions/s2/messages",
        ]
        # The second s1 request continues from the last yielded message id.
        assert params[2]["params"]["after"] == "m2"
        assert "after" not in params[3]["params"]

    @mock.patch(SESSION_PATCH)
    def test_checkpoints_track_fanout_progress(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"sessions": [{"id": "s1"}, {"id": "s2"}]}),
                _response({"messages": [{"id": "m1"}, {"id": "m2"}], "hasMore": True}),
                _response({"messages": [{"id": "m3"}], "hasMore": False}),
                _response({"messages": [{"id": "m9"}], "hasMore": False}),
            ],
        )

        manager = _make_manager()
        _rows(_source("session_messages", manager))

        saved = [call.args[0].fanout_state for call in manager.save_state.call_args_list]
        # Mid-s1 the checkpoint carries the in-progress cursor so a crash resumes from m2.
        assert {
            "completed": [],
            "current": "/sessions/s1/messages",
            "child_state": {"after": "m2"},
        } in saved
        # The final checkpoint marks both sessions completed.
        assert saved[-1] == {
            "completed": ["/sessions/s1/messages", "/sessions/s2/messages"],
            "current": None,
            "child_state": None,
        }

    @mock.patch(SESSION_PATCH)
    def test_resumes_cursor_within_bookmarked_session(self, MockSession) -> None:
        # A crash mid-s2 leaves completed=[s1] plus s2's `after` cursor; on resume s2 must continue
        # from m8 (not restart) while the already-completed s1 is skipped.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"sessions": [{"id": "s1"}, {"id": "s2"}]}),
                _response({"messages": [{"id": "m9"}], "hasMore": False}),
            ],
        )

        manager = _make_manager(
            BrowserUseResumeConfig(
                fanout_state={
                    "completed": ["/sessions/s1/messages"],
                    "current": "/sessions/s2/messages",
                    "child_state": {"after": "m8"},
                }
            )
        )
        rows = _rows(_source("session_messages", manager))

        assert [(r["id"], r["sessionId"]) for r in rows] == [("m9", "s2")]
        assert params[1]["url"] == f"{BROWSER_USE_BASE_URL}/sessions/s2/messages"
        assert params[1]["params"]["after"] == "m8"

    @mock.patch(SESSION_PATCH)
    def test_completed_sessions_are_skipped_on_resume(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"sessions": [{"id": "s1"}, {"id": "s2"}]}),
                _response({"messages": [{"id": "m9"}], "hasMore": False}),
            ],
        )

        manager = _make_manager(
            BrowserUseResumeConfig(
                fanout_state={"completed": ["/sessions/s1/messages"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source("session_messages", manager))

        assert [(r["id"], r["sessionId"]) for r in rows] == [("m9", "s2")]
        assert [p["url"] for p in params] == [
            f"{BROWSER_USE_BASE_URL}/sessions",
            f"{BROWSER_USE_BASE_URL}/sessions/s2/messages",
        ]

    @mock.patch(SESSION_PATCH)
    def test_legacy_resume_state_restarts_fanout(self, MockSession) -> None:
        # State saved before the framework migration bookmarked a session id + `after` cursor.
        # It still parses (the dataclass keeps the fields) but restarts the fan-out fresh —
        # merge dedupes the re-pulled rows.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"sessions": [{"id": "s1"}]}),
                _response({"messages": [{"id": "m1"}], "hasMore": False}),
            ],
        )

        manager = _make_manager(BrowserUseResumeConfig(session_id="s1", after="m0"))
        rows = _rows(_source("session_messages", manager))

        assert [r["id"] for r in rows] == ["m1"]
        assert "after" not in params[1]["params"]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SESSION_PATCH)
    def test_retryable_status_retries_then_raises(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status) for _ in range(5)])

        with mock.patch.object(RESTClient._send_request.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(RESTClientRetryableError):
                _rows(_source("sessions"))
        # Retried up to the 5-attempt cap before giving up.
        assert session.send.call_count == 5

    @mock.patch(SESSION_PATCH)
    def test_client_error_raises_for_status(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=401)])

        # A credential error is terminal — no retry, and the message carries the stable
        # "401 Client Error: Unauthorized for url: <base host>" prefix the source's
        # get_non_retryable_errors classifier matches on.
        with pytest.raises(
            requests.HTTPError, match="401 Client Error: Unauthorized for url: https://api.browser-use.com"
        ):
            _rows(_source("sessions"))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(SESSION_PATCH)
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("bu_test") is expected

    @mock.patch(SESSION_PATCH)
    def test_network_error_is_false(self, MockSession) -> None:
        MockSession.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("bu_test") is False


class TestSessionHardening:
    # Every Browser Use endpoint returns free-form agent content — session titles and
    # session_messages.data hold whatever a user's agent typed or browsed, which the name-based
    # scrubbers can't recognise — so both the export path and the credential probe must build
    # their tracked session with capture=False. And the API key rides in the custom
    # X-Browser-Use-API-Key header, which requests preserves across a cross-host 3xx (it only
    # strips Authorization), so both must also pin allow_redirects=False. A regression that drops
    # either flag re-opens the corresponding leak.
    @mock.patch(SESSION_PATCH)
    def test_source_session_disables_capture_and_redirects(self, MockSession) -> None:
        _source("sessions")

        kwargs = MockSession.call_args.kwargs
        assert kwargs["capture"] is False
        assert kwargs["allow_redirects"] is False
        assert kwargs["redact_values"] == ("bu_test",)

    @mock.patch(SESSION_PATCH)
    def test_validate_credentials_disables_capture_and_redirects(self, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("bu_test")

        kwargs = MockSession.call_args.kwargs
        assert kwargs["capture"] is False
        assert kwargs["allow_redirects"] is False


class TestSourceResponse:
    @parameterized.expand(
        [
            ("sessions", ["id"], "createdAt"),
            ("browser_sessions", ["id"], "startedAt"),
            ("profiles", ["id"], "createdAt"),
            ("workspaces", ["id"], "createdAt"),
            ("session_messages", ["sessionId", "id"], "createdAt"),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_primary_keys_and_partition(
        self, endpoint: str, primary_keys: list[str], partition_key: str, MockSession
    ) -> None:
        MockSession.return_value.headers = {}
        response = _source(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"
