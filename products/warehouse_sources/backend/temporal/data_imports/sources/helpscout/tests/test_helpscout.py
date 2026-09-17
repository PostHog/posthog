import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.helpscout import (
    HELP_SCOUT_API_BASE,
    HelpScoutResumeConfig,
    _client_config,
    helpscout_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.settings import (
    ENDPOINTS,
    HELP_SCOUT_ENDPOINTS,
)

# RESTClient builds its HTTP session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# OAuth2Auth mints its token through make_tracked_session in the rest_source auth module.
AUTH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
)
# validate_credentials builds its probe session via make_tracked_session in the helpscout module.
HELPSCOUT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.helpscout.make_tracked_session"
)
# threads' fan-out is driven through the shared fanout helper's rest_api_resources call.
FANOUT_RESOURCES_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
)


def _response(embedded_key: str, items: list[dict[str, Any]], next_url: str | None = None) -> Response:
    body: dict[str, Any] = {"_embedded": {embedded_key: items}, "_links": {}}
    if next_url:
        body["_links"]["next"] = {"href": next_url}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = f"{HELP_SCOUT_API_BASE}/probe"
    return resp


def _bare_response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = f"{HELP_SCOUT_API_BASE}/probe"
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b"{}"
    resp.url = f"{HELP_SCOUT_API_BASE}/conversations"
    return resp


def _manager(resume_state: HelpScoutResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session and snapshot each request's url + params AT PREPARE TIME.

    ``prepare_request`` is mocked, which bypasses the auth callable entirely — these tests exercise
    pagination/fan-out/resume, not token minting (covered separately in TestValidateCredentials).
    ``request.params`` is one dict mutated in place across pages, so snapshot a copy per request.
    The stand-in prepared request carries the real URL string: the client host-checks
    ``prepared.url`` before sending, and a bare MagicMock there would not be a URL at all.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return helpscout_source("token", endpoint, team_id=1, job_id="job-1", resumable_source_manager=manager, **kwargs)


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestAuth:
    def test_client_config_sends_bearer_token(self) -> None:
        # The token now comes from the Integration, so the source must not mint its own.
        auth = _client_config("token")["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "token"

    def test_client_config_pins_requests_to_the_api_host(self) -> None:
        # Pagination follows `_links.next.href` out of the response body, so the client must
        # refuse off-host URLs and redirects rather than replay the bearer token elsewhere.
        config = _client_config("token")
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False

    def test_client_config_excludes_requests_from_sample_capture(self) -> None:
        # Conversation subjects and thread bodies are free-text, customer-authored support
        # content, so responses must not land in HTTP sample capture.
        assert _client_config("token")["capture"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_link_is_rejected(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response("mailboxes", [{"id": 1}], next_url="https://evil.example.com/v2/mailboxes?page=2"),
                _response("mailboxes", [{"id": 2}]),
            ],
        )

        with pytest.raises(ValueError, match="evil.example.com"):
            _rows(_source("mailboxes", _manager()))


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_hal_next_link(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{HELP_SCOUT_API_BASE}/mailboxes?page=2"
        urls, _params = _wire(
            session,
            [
                _response("mailboxes", [{"id": 1}, {"id": 2}], next_url=next_url),
                _response("mailboxes", [{"id": 3}]),
            ],
        )

        rows = _rows(_source("mailboxes", _manager()))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert urls[1] == next_url
        manager_calls = session.send.call_count
        assert manager_calls == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_uses_endpoint_path_with_no_params(self, MockSession) -> None:
        session = MockSession.return_value
        urls, params = _wire(session, [_response("tags", [])])

        _rows(_source("tags", _manager()))

        assert urls[0] == f"{HELP_SCOUT_API_BASE}/tags"
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = f"{HELP_SCOUT_API_BASE}/users?page=3"
        urls, params = _wire(session, [_response("users", [{"id": 9}])])

        manager = _manager(HelpScoutResumeConfig(next_url=resume_url))
        _rows(_source("users", manager))

        assert urls[0] == resume_url
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_non_terminal_page(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{HELP_SCOUT_API_BASE}/workflows?page=2"
        _wire(
            session,
            [
                _response("workflows", [{"id": 1}], next_url=next_url),
                _response("workflows", [{"id": 2}]),
            ],
        )

        manager = _manager()
        _rows(_source("workflows", manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == HelpScoutResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminal_single_page_saves_no_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("tags", [{"id": 1}])])

        manager = _manager()
        _rows(_source("tags", manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_embedded_block_yields_nothing(self, MockSession) -> None:
        # A 200 body without an `_embedded` block is a legitimate empty page, not an error.
        session = MockSession.return_value
        _wire(session, [_bare_response({"page": {"totalElements": 0}, "_links": {}})])

        rows = _rows(_source("mailboxes", _manager()))

        assert rows == []


class TestIncrementalParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_conversations_incremental_sends_modified_since_and_sort(self, MockSession) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response("conversations", [])])

        _rows(
            _source(
                "conversations",
                _manager(),
                should_use_incremental_field=True,
                incremental_field="modifiedAt",
                db_incremental_field_last_value="2024-01-01T00:00:00Z",
            )
        )

        assert params[0]["modifiedSince"] == "2024-01-01T00:00:00Z"
        assert params[0]["sortField"] == "modifiedAt"
        assert params[0]["sortOrder"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_conversations_full_refresh_sorts_on_created_at(self, MockSession) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response("conversations", [])])

        _rows(_source("conversations", _manager()))

        assert "modifiedSince" not in params[0]
        assert params[0]["sortField"] == "createdAt"
        assert params[0]["sortOrder"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_customers_incremental_sends_modified_since(self, MockSession) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response("customers", [])])

        _rows(
            _source(
                "customers",
                _manager(),
                should_use_incremental_field=True,
                incremental_field="modifiedAt",
                db_incremental_field_last_value="2024-06-01T00:00:00Z",
            )
        )

        assert params[0]["modifiedSince"] == "2024-06-01T00:00:00Z"

    @pytest.mark.parametrize("endpoint", ["mailboxes", "users", "tags", "workflows"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoints_without_sort_support_send_no_extra_params(self, MockSession, endpoint) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response(HELP_SCOUT_ENDPOINTS[endpoint].embedded_key, [])])

        _rows(_source(endpoint, _manager()))

        assert params[0] == {}


class TestRetries:
    @pytest.mark.parametrize("retryable_status", [429, 500, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_triggers_retry_then_succeeds(self, MockSession, _mock_sleep, retryable_status) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(retryable_status), _response("conversations", [{"id": 1}])])

        rows = _rows(_source("conversations", _manager()))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_4xx_raises_immediately(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(403)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("conversations", _manager()))

        assert session.send.call_count == 1


class _FakeResource:
    def __init__(self, name: str) -> None:
        self.name = name
        self.maps: list[Any] = []

    def add_map(self, fn: Any) -> "_FakeResource":
        self.maps.append(fn)
        return self


class TestThreadsFanout:
    def _build(self, **kwargs: Any) -> tuple[_FakeResource, list[Any]]:
        child = _FakeResource("threads")
        with mock.patch(FANOUT_RESOURCES_PATCH, return_value=[_FakeResource("conversations"), child]) as mocked:
            helpscout_source(
                "token", "threads", team_id=1, job_id="job-1", resumable_source_manager=_manager(), **kwargs
            )
        return child, mocked.call_args[0]

    def test_parent_and_child_endpoints(self) -> None:
        _, args = self._build()
        parent, child = args[0]["resources"]

        assert parent["endpoint"]["path"] == "/conversations"
        assert child["endpoint"]["path"] == "/conversations/{conversation_id}/threads"
        assert child["endpoint"]["params"]["conversation_id"] == {
            "type": "resolve",
            "resource": "conversations",
            "field": "id",
        }
        assert child["include_from_parent"] == ["id"]
        # Help Scout has no page-size param; neither endpoint should send one.
        assert "limit" not in parent["endpoint"]["params"]
        assert "limit" not in child["endpoint"]["params"]

    def test_thread_rows_carry_the_parent_conversation_id(self) -> None:
        child, _ = self._build()

        row = child.maps[0]({"_conversations_id": 42, "id": 7, "body": "hi"})

        assert row == {"conversation_id": 42, "id": 7, "body": "hi"}

    def test_resume_seeds_fanout_state(self) -> None:
        state = {"completed": ["/conversations/1/threads"], "current": None, "child_state": None}
        manager = _manager(HelpScoutResumeConfig(fanout_state=state))
        child = _FakeResource("threads")

        with mock.patch(FANOUT_RESOURCES_PATCH, return_value=[_FakeResource("conversations"), child]) as mocked:
            helpscout_source("token", "threads", team_id=1, job_id="job-1", resumable_source_manager=manager)

        assert mocked.call_args.kwargs["initial_paginator_state"] == state

    def test_checkpoints_fanout_progress(self) -> None:
        manager = _manager()
        child = _FakeResource("threads")

        with mock.patch(FANOUT_RESOURCES_PATCH, return_value=[_FakeResource("conversations"), child]) as mocked:
            helpscout_source("token", "threads", team_id=1, job_id="job-1", resumable_source_manager=manager)
            resume_hook = mocked.call_args.kwargs["resume_hook"]
            resume_hook({"completed": ["/conversations/1/threads"], "current": None, "child_state": None})

        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved.fanout_state == {"completed": ["/conversations/1/threads"], "current": None, "child_state": None}


class TestSourceResponseShape:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_top_level_endpoint(self, _MockSession) -> None:
        for endpoint in ENDPOINTS:
            if endpoint == "threads":
                continue
            config = HELP_SCOUT_ENDPOINTS[endpoint]
            response = _source(endpoint, _manager())

            assert response.name == endpoint
            assert response.primary_keys == config.primary_key
            assert response.sort_mode == "asc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["createdAt"]

    def test_threads_response_uses_composite_primary_key(self) -> None:
        with mock.patch(
            FANOUT_RESOURCES_PATCH, return_value=[_FakeResource("conversations"), _FakeResource("threads")]
        ):
            response = _source("threads", _manager())

        assert response.primary_keys == ["conversation_id", "id"]


class TestValidateCredentials:
    @mock.patch(HELPSCOUT_SESSION_PATCH)
    def test_source_create_probes_users_me(self, helpscout_session) -> None:
        helpscout_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        ok, error = validate_credentials("token", schema_name=None)

        assert ok is True
        assert error is None
        assert helpscout_session.return_value.get.call_args.args[0].endswith("/users/me")

    @mock.patch(HELPSCOUT_SESSION_PATCH)
    def test_probe_sessions_exclude_sample_capture(self, helpscout_session) -> None:
        # /users/me and the schema probes can return customer-authored free-text content
        # (e.g. a conversation subject), so neither must land in HTTP sample capture.
        helpscout_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("token", schema_name=None)
        assert helpscout_session.call_args.kwargs["capture"] is False

        validate_credentials("token", schema_name="mailboxes")
        assert helpscout_session.call_args.kwargs["capture"] is False

    @mock.patch(HELPSCOUT_SESSION_PATCH)
    def test_revoked_token_fails_at_source_create(self, helpscout_session) -> None:
        helpscout_session.return_value.get.return_value = mock.MagicMock(status_code=401)

        ok, error = validate_credentials("token", schema_name=None)

        assert ok is False
        assert error is not None

    @mock.patch(HELPSCOUT_SESSION_PATCH)
    def test_schema_probe_success(self, helpscout_session) -> None:
        helpscout_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        ok, error = validate_credentials("token", schema_name="mailboxes")

        assert ok is True
        assert error is None

    @mock.patch(HELPSCOUT_SESSION_PATCH)
    def test_schema_probe_401_reports_auth_error(self, helpscout_session) -> None:
        helpscout_session.return_value.get.return_value = mock.MagicMock(status_code=401)

        ok, error = validate_credentials("token", schema_name="mailboxes")

        assert ok is False
        assert error is not None and "authentication failed" in error

    @mock.patch(HELPSCOUT_SESSION_PATCH)
    def test_unknown_schema_fails_without_probing(self, helpscout_session) -> None:
        helpscout_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        ok, error = validate_credentials("token", schema_name="not_a_table")

        assert ok is False
        assert error == "Unknown Help Scout table 'not_a_table'"
        helpscout_session.return_value.get.assert_not_called()

    @mock.patch(HELPSCOUT_SESSION_PATCH)
    def test_threads_probe_uses_conversations_endpoint(self, helpscout_session) -> None:
        helpscout_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        ok, _error = validate_credentials("token", schema_name="threads")

        assert ok is True
        probed_url = helpscout_session.return_value.get.call_args.args[0]
        assert probed_url == f"{HELP_SCOUT_API_BASE}/conversations"
