import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny import (
    PAGE_SIZE,
    CannyBodyAuth,
    CannyResumeConfig,
    canny_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the canny module.
CANNY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny.make_tracked_session"
)


def _response(body: Any, status: int = 200, reason: str = "") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = "https://canny.io/api/v1/posts/list"
    resp._content = json.dumps(body).encode()
    return resp


def _page(key: str, ids: list[str], has_more: bool) -> Response:
    return _response({key: [{"id": i} for i in ids], "hasMore": has_more})


def _full_page(key: str, start: int, has_more: bool = True) -> Response:
    return _page(key, [str(i) for i in range(start, start + PAGE_SIZE)], has_more)


def _make_manager(resume_state: CannyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's JSON body AT SEND TIME.

    ``request.json`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(dict(request.json or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, api_key: str = "k"):
    return canny_source(api_key=api_key, endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestCannyBodyAuth:
    def test_injects_api_key_into_existing_json_body(self) -> None:
        request = requests.Request(
            method="POST",
            url="https://canny.io/api/v1/posts/list",
            json={"skip": 0, "limit": PAGE_SIZE},
            auth=CannyBodyAuth("secret"),
        )
        prepared = requests.Session().prepare_request(request)
        assert json.loads(prepared.body) == {"skip": 0, "limit": PAGE_SIZE, "apiKey": "secret"}

    def test_creates_body_when_absent(self) -> None:
        # boards/list sends no pagination params, so the body is just the key.
        request = requests.Request(
            method="POST", url="https://canny.io/api/v1/boards/list", auth=CannyBodyAuth("secret")
        )
        prepared = requests.Session().prepare_request(request)
        assert json.loads(prepared.body) == {"apiKey": "secret"}

    def test_declares_api_key_as_secret_for_redaction(self) -> None:
        assert CannyBodyAuth("secret").secret_values() == ("secret",)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_has_more_false_and_saves_after_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(
            session,
            [_full_page("posts", 0), _full_page("posts", PAGE_SIZE), _page("posts", ["final"], has_more=False)],
        )

        manager = _make_manager()
        rows = _rows(_source("posts", manager))

        assert [r["id"] for r in rows] == [*(str(i) for i in range(2 * PAGE_SIZE)), "final"]
        assert [b.get("skip") for b in bodies] == [0, PAGE_SIZE, PAGE_SIZE * 2]
        assert all(b.get("limit") == PAGE_SIZE for b in bodies)
        # State is saved after each non-terminal page so a crash re-yields rather than skips.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CannyResumeConfig(skip=PAGE_SIZE), CannyResumeConfig(skip=PAGE_SIZE * 2)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_with_has_more_false_stops_without_extra_request(self, MockSession) -> None:
        # Termination is driven by Canny's hasMore flag, not page size — a full last page must
        # not trigger a wasted empty-page probe.
        session = MockSession.return_value
        _wire(session, [_full_page("posts", 0, has_more=False)])

        rows = _rows(_source("posts", _make_manager()))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_skip_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_page("posts", ["x"], has_more=False)])

        manager = _make_manager(CannyResumeConfig(skip=PAGE_SIZE * 2))
        rows = _rows(_source("posts", manager))

        assert bodies[0].get("skip") == PAGE_SIZE * 2
        manager.load_state.assert_called_once()
        assert [r["id"] for r in rows] == ["x"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminal_single_page_does_not_save_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("posts", ["only"], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source("posts", manager))

        assert [r["id"] for r in rows] == ["only"]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_fetches_once_without_pagination_params(self, MockSession) -> None:
        session = MockSession.return_value
        # boards/list has no hasMore flag; a single fetch must terminate the loop.
        bodies = _wire(session, [_response({"boards": [{"id": "b1"}]})])

        manager = _make_manager()
        rows = _rows(_source("boards", manager))

        assert session.send.call_count == 1
        assert "skip" not in bodies[0]
        assert "limit" not in bodies[0]
        assert rows == [{"id": "b1"}]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("posts", [], has_more=False)])

        manager = _make_manager()
        assert _rows(_source("posts", manager)) == []
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize(
        "body",
        [{}, {"posts": None}, {"posts": {"id": "1"}}, {"other": [{"id": "1"}]}],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_or_non_list_data_key_yields_nothing(self, MockSession, body: dict[str, Any]) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        assert _rows(_source("posts", _make_manager())) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_error_body_on_200_raises_http_error(self, MockSession) -> None:
        # Canny can return 200 with an {"error": ...} body for a bad API key; the message must
        # carry the error text so the friendly non-retryable mapping can match it.
        session = MockSession.return_value
        _wire(session, [_response({"error": "invalid API key"})])

        with pytest.raises(requests.HTTPError, match="invalid API key"):
            _rows(_source("posts", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_error_body_on_unpaginated_endpoint_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "invalid API key"})])

        with pytest.raises(requests.HTTPError, match="invalid API key"):
            _rows(_source("boards", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_registers_api_key_for_redaction(self, MockSession) -> None:
        # The secret rides in the POST body through the tracked transport; it must be redacted so
        # it never lands in HTTP logs/samples.
        session = MockSession.return_value
        _wire(session, [_page("posts", [], has_more=False)])

        _rows(_source("posts", _make_manager(), api_key="secret"))

        MockSession.assert_called_once_with(redact_values=("secret",))


class TestRetries:
    @pytest.mark.parametrize("status", [429, 500, 503])
    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, MockSession, _sleep, status: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status), _page("posts", ["a"], has_more=False)])

        rows = _rows(_source("posts", _make_manager()))

        assert [r["id"] for r in rows] == ["a"]
        assert session.send.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_exhaust_then_raise(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=500)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("posts", _make_manager()))
        assert session.send.call_count == 5

    @pytest.mark.parametrize(
        ("status", "reason"),
        [(400, "Bad Request"), (401, "Unauthorized"), (403, "Forbidden")],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error_without_retry(self, MockSession, status: int, reason: str) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError, match=f"{status} Client Error"):
            _rows(_source("posts", _make_manager()))
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unauthorized_message_matches_non_retryable_mapping(self, MockSession) -> None:
        # source.py maps this exact substring to the friendly invalid-key message.
        session = MockSession.return_value
        _wire(session, [_response({}, status=401, reason="Unauthorized")])

        with pytest.raises(requests.HTTPError, match="401 Client Error: Unauthorized for url: https://canny.io"):
            _rows(_source("posts", _make_manager()))


class TestValidateCredentials:
    def _validate(self, response: Any = None, raises: Exception | None = None) -> bool:
        with mock.patch(CANNY_SESSION_PATCH) as MockSession:
            post = MockSession.return_value.post
            if raises is not None:
                post.side_effect = raises
            else:
                post.return_value = response
            return validate_credentials("k")

    def test_valid_key(self) -> None:
        assert self._validate(_response({"boards": []})) is True

    def test_error_body_is_invalid(self) -> None:
        assert self._validate(_response({"error": "invalid API key"})) is False

    def test_non_ok_is_invalid(self) -> None:
        assert self._validate(_response({}, status=401)) is False

    def test_network_error_is_invalid(self) -> None:
        assert self._validate(raises=requests.ConnectionError("boom")) is False

    def test_registers_api_key_for_redaction(self) -> None:
        with mock.patch(CANNY_SESSION_PATCH) as MockSession:
            MockSession.return_value.post.return_value = _response({"boards": []})
            validate_credentials("secret")

        MockSession.assert_called_once_with(redact_values=("secret",))


class TestCannySource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Every Canny object carries a stable `created` timestamp we partition on.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]
