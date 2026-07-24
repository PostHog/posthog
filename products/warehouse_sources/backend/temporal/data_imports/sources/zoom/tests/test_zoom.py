import json
from typing import Any, cast

from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.zoom import (
    ZOOM_API_BASE,
    ZOOM_OAUTH_URL,
    ZoomResumeConfig,
    _oauth_auth,
    validate_credentials,
    zoom_source,
)

# RESTClient builds its HTTP session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# OAuth2Auth mints its token through make_tracked_session in the rest_source auth module.
AUTH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
)
# validate_credentials builds its probe session via make_tracked_session in the zoom module.
ZOOM_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.zoom.zoom.make_tracked_session"


def _resp(body: dict[str, Any], status: int = 200) -> Response:
    response = Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _manager(can_resume: bool = False, state: ZoomResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire the mock session and capture each request's URL and params AT SEND TIME.

    ``prepare_request`` is mocked, which bypasses the auth callable — the data-flow tests exercise
    pagination/fan-out/resume, not token minting (covered separately). ``request.params`` is one dict
    mutated in place across pages, so snapshot a copy per request rather than reading it after the run.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _rows(source_response: Any) -> list[list[dict[str, Any]]]:
    return list(source_response.items())


def _source(endpoint: str, manager: MagicMock) -> Any:
    return zoom_source("acc", "cid", "secret", endpoint, team_id=1, job_id="job-1", resumable_source_manager=manager)


class TestZoomResumeConfig:
    def test_defaults(self) -> None:
        assert ZoomResumeConfig() == ZoomResumeConfig(next_page_token="", user_index=0, fanout_state=None)

    def test_legacy_state_still_deserializes(self) -> None:
        # State saved by the previous implementation carried only next_page_token / user_index; the
        # added fanout_state field must default so ResumableSourceManager can still rebuild it.
        assert ZoomResumeConfig(next_page_token="tok", user_index=3) == ZoomResumeConfig(
            next_page_token="tok", user_index=3, fanout_state=None
        )


class TestOAuthConfig:
    def test_builds_server_to_server_oauth(self) -> None:
        auth = _oauth_auth("acc-1", "client-1", "secret-1")
        assert auth.token_url == ZOOM_OAUTH_URL
        assert auth.client_id == "client-1"
        assert auth.client_secret == "secret-1"
        assert cast(str, auth.grant_type) == "account_credentials"
        assert auth.client_auth_method == "basic"
        assert auth.extra_token_request_params == {"account_id": "acc-1"}


class TestTopLevelRows:
    @patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_yields_each_page(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        _wire(
            session,
            [
                _resp({"users": [{"id": "u1"}], "next_page_token": "t1"}),
                _resp({"users": [{"id": "u2"}], "next_page_token": ""}),
            ],
        )

        rows = _rows(_source("users", _manager()))
        assert rows == [[{"id": "u1"}], [{"id": "u2"}]]

    @patch(CLIENT_SESSION_PATCH)
    def test_first_request_omits_token_then_carries_cursor(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        _, params = _wire(
            session,
            [
                _resp({"users": [{"id": "u1"}], "next_page_token": "t1"}),
                _resp({"users": [{"id": "u2"}], "next_page_token": ""}),
            ],
        )

        _rows(_source("users", _manager()))
        assert "next_page_token" not in params[0]
        assert params[0]["page_size"] == 300
        assert params[1]["next_page_token"] == "t1"

    @patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_non_terminal_page(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        _wire(
            session,
            [
                _resp({"users": [{"id": "u1"}], "next_page_token": "t1"}),
                _resp({"users": [{"id": "u2"}], "next_page_token": ""}),
            ],
        )

        manager = _manager()
        _rows(_source("users", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ZoomResumeConfig(next_page_token="t1")]

    @patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_first_request_with_saved_token(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        _, params = _wire(session, [_resp({"users": [{"id": "u9"}], "next_page_token": ""})])

        manager = _manager(can_resume=True, state=ZoomResumeConfig(next_page_token="resumed"))
        _rows(_source("users", manager))

        assert params[0]["next_page_token"] == "resumed"
        manager.load_state.assert_called_once()

    @patch(CLIENT_SESSION_PATCH)
    def test_terminal_single_page_saves_no_state(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        _wire(session, [_resp({"users": [{"id": "u1"}], "next_page_token": ""})])

        manager = _manager()
        _rows(_source("users", manager))

        manager.save_state.assert_not_called()


class TestFanOutRows:
    @patch(CLIENT_SESSION_PATCH)
    def test_fans_out_meetings_per_user(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        urls, params = _wire(
            session,
            [
                _resp({"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""}),
                _resp({"meetings": [{"id": 1}], "next_page_token": ""}),
                _resp({"meetings": [{"id": 2}], "next_page_token": ""}),
            ],
        )

        rows = _rows(_source("meetings", _manager()))

        assert rows == [[{"id": 1}], [{"id": 2}]]
        assert urls == [
            f"{ZOOM_API_BASE}/users",
            f"{ZOOM_API_BASE}/users/u1/meetings",
            f"{ZOOM_API_BASE}/users/u2/meetings",
        ]
        # The scheduled-meetings filter rides on every child request.
        assert params[1]["type"] == "scheduled"

    @patch(CLIENT_SESSION_PATCH)
    def test_skips_user_lacking_feature(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        urls, _ = _wire(
            session,
            [
                _resp({"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""}),
                _resp({"code": 200, "message": "no webinar plan"}, status=400),
                _resp({"webinars": [{"id": 9}], "next_page_token": ""}),
            ],
        )

        rows = _rows(_source("webinars", _manager()))

        # The unlicensed user is skipped (400) without aborting the sync.
        assert rows == [[{"id": 9}]]
        assert f"{ZOOM_API_BASE}/users/u1/webinars" in urls
        assert f"{ZOOM_API_BASE}/users/u2/webinars" in urls

    @patch(CLIENT_SESSION_PATCH)
    def test_skips_user_on_404(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        _wire(
            session,
            [
                _resp({"users": [{"id": "u1"}], "next_page_token": ""}),
                _resp({"code": 1001, "message": "user not found"}, status=404),
            ],
        )

        rows = _rows(_source("webinars", _manager()))
        assert rows == []

    @patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_users(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        _wire(
            session,
            [
                _resp({"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""}),
                _resp({"meetings": [{"id": 1}], "next_page_token": ""}),
                _resp({"meetings": [{"id": 2}], "next_page_token": ""}),
            ],
        )

        manager = _manager()
        _rows(_source("meetings", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved, "expected fan-out progress to be checkpointed"
        # The final checkpoint records both users as completed.
        final = saved[-1]
        assert final.fanout_state is not None
        assert final.fanout_state["completed"] == ["/users/u1/meetings", "/users/u2/meetings"]
        assert final.fanout_state["current"] is None

    @patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_already_completed_user(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        urls, _ = _wire(
            session,
            [
                _resp({"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""}),
                _resp({"meetings": [{"id": 2}], "next_page_token": ""}),
            ],
        )

        state = ZoomResumeConfig(
            fanout_state={"completed": ["/users/u1/meetings"], "current": None, "child_state": None}
        )
        manager = _manager(can_resume=True, state=state)
        rows = _rows(_source("meetings", manager))

        # u1 was already completed, so its meetings endpoint is never requested again.
        assert rows == [[{"id": 2}]]
        assert f"{ZOOM_API_BASE}/users/u1/meetings" not in urls
        assert f"{ZOOM_API_BASE}/users/u2/meetings" in urls


class TestZoomSourceResponse:
    @patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, _mock_session: MagicMock) -> None:
        response = _source("users", _manager())
        assert response.name == "users"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "week"

    @patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_per_endpoint(self, _mock_session: MagicMock) -> None:
        for endpoint in ("users", "meetings", "webinars"):
            response = _source(endpoint, _manager())
            assert response.primary_keys == ["id"]


class TestValidateCredentials:
    def _token_resp(self, status: int = 200, payload: dict[str, Any] | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.raw.read.return_value = json.dumps(
            payload if payload is not None else {"access_token": "tok", "expires_in": 3599}
        ).encode()
        return response

    @patch(AUTH_SESSION_PATCH)
    def test_bad_credentials_return_false(self, auth_session: MagicMock) -> None:
        auth_session.return_value.post.return_value = self._token_resp(status=400, payload={"error": "invalid_client"})
        ok, error = validate_credentials("acc", "cid", "secret")
        assert ok is False
        assert error is not None

    @patch(ZOOM_SESSION_PATCH)
    @patch(AUTH_SESSION_PATCH)
    def test_source_create_only_validates_token(self, auth_session: MagicMock, zoom_session: MagicMock) -> None:
        auth_session.return_value.post.return_value = self._token_resp()
        ok, error = validate_credentials("acc", "cid", "secret", schema_name=None)
        assert ok is True
        assert error is None
        # No scoped endpoint probe at source-create.
        zoom_session.return_value.get.assert_not_called()

    @patch(ZOOM_SESSION_PATCH)
    @patch(AUTH_SESSION_PATCH)
    def test_schema_probe_success(self, auth_session: MagicMock, zoom_session: MagicMock) -> None:
        auth_session.return_value.post.return_value = self._token_resp()
        zoom_session.return_value.get.return_value = MagicMock(status_code=200)
        ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is True
        assert error is None

    @patch(ZOOM_SESSION_PATCH)
    @patch(AUTH_SESSION_PATCH)
    def test_schema_probe_missing_scope_401(self, auth_session: MagicMock, zoom_session: MagicMock) -> None:
        auth_session.return_value.post.return_value = self._token_resp()
        zoom_session.return_value.get.return_value = MagicMock(status_code=401)
        ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is False
        assert error is not None and "scope" in error

    @patch(ZOOM_SESSION_PATCH)
    @patch(AUTH_SESSION_PATCH)
    def test_schema_probe_missing_scope_403(self, auth_session: MagicMock, zoom_session: MagicMock) -> None:
        auth_session.return_value.post.return_value = self._token_resp()
        zoom_session.return_value.get.return_value = MagicMock(status_code=403)
        ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is False
        assert error is not None and "scope" in error

    @patch(ZOOM_SESSION_PATCH)
    @patch(AUTH_SESSION_PATCH)
    def test_schema_probe_unexpected_status(self, auth_session: MagicMock, zoom_session: MagicMock) -> None:
        auth_session.return_value.post.return_value = self._token_resp()
        zoom_session.return_value.get.return_value = MagicMock(status_code=500)
        ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is False
        assert error is not None and "500" in error
