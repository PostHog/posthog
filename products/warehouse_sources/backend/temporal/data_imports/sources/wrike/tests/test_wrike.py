import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike import (
    WrikeResumeConfig,
    _build_url,
    is_host_valid,
    validate_credentials,
    wrike_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the wrike module.
WRIKE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike.make_tracked_session"
)


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: WrikeResumeConfig | None = None, can_resume: bool = False) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume or resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of reading it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        # The client host-pins every request URL (allowed_hosts), so the prepared request must
        # carry a real Wrike URL rather than a bare MagicMock.
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, host: str = "www.wrike.com", **kwargs: Any):
    manager = kwargs.pop("manager", None) or _make_manager()
    return wrike_source("token", host, endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestIsHostValid:
    @pytest.mark.parametrize(
        "host, expected",
        [
            ("www.wrike.com", True),
            ("app-us2.wrike.com", True),
            ("app-eu.wrike.com", True),
            ("https://www.wrike.com/", True),
            ("WWW.WRIKE.COM", True),
            ("www.wrike.com:443", True),
            ("evil.com", False),
            ("wrike.com.evil.com", False),
            ("notwrike.com", False),
            ("localhost", False),
            ("169.254.169.254", False),
            ("", False),
            # SSRF bypass attempts: a path/query/credentials must not smuggle a non-Wrike
            # netloc past the suffix check.
            ("evil.com?.wrike.com", False),
            ("evil.com/.wrike.com", False),
            ("internal.service/path.wrike.com", False),
            ("evil.com#.wrike.com", False),
            ("user:pass@evil.com", False),
            ("user@evil.com:443", False),
        ],
    )
    def test_is_host_valid(self, host: str, expected: bool) -> None:
        assert is_host_valid(host) is expected

    @pytest.mark.parametrize(
        "host",
        ["evil.com?.wrike.com", "internal.service/path.wrike.com", "user:pass@evil.com.attacker.net"],
    )
    def test_build_url_target_never_diverges_from_validation(self, host: str) -> None:
        # The connection target is built from the same normalized hostname is_host_valid checks,
        # so a host that fails validation can never resolve to a Wrike URL.
        assert is_host_valid(host) is False
        assert "wrike.com/api/v4" not in _build_url(host, "/tasks", {})


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("www.wrike.com", "/tasks", {}) == "https://www.wrike.com/api/v4/tasks"

    def test_with_params(self) -> None:
        url = _build_url("www.wrike.com", "/tasks", {"pageSize": 1000})
        assert url == "https://www.wrike.com/api/v4/tasks?pageSize=1000"

    def test_drops_none_values(self) -> None:
        url = _build_url("app-us2.wrike.com", "/tasks", {"pageSize": 1000, "nextPageToken": None})
        assert url == "https://app-us2.wrike.com/api/v4/tasks?pageSize=1000"

    def test_normalizes_scheme_and_trailing_slash(self) -> None:
        assert _build_url("https://www.wrike.com/", "/contacts", {}) == "https://www.wrike.com/api/v4/contacts"


class TestValidateCredentials:
    def test_rejects_non_wrike_host_without_request(self) -> None:
        with mock.patch(WRIKE_SESSION_PATCH) as make_session:
            is_valid, error = validate_credentials("token", "evil.com")
        assert is_valid is False
        assert error is not None and "Wrike domain" in error
        make_session.assert_not_called()

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_error",
        [
            (200, True, None),
            (401, False, "Invalid Wrike access token"),
            (403, False, "Wrike access token is missing the required permissions"),
            (500, False, "Wrike API error: status=500"),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_error: str | None) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(WRIKE_SESSION_PATCH, return_value=session):
            is_valid, error = validate_credentials("token", "www.wrike.com")
        assert is_valid is expected_valid
        assert error == expected_error

    def test_swallows_transport_errors(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(WRIKE_SESSION_PATCH, return_value=session):
            is_valid, _error = validate_credentials("token", "www.wrike.com")
        assert is_valid is False

    def test_probes_current_user_endpoint(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(WRIKE_SESSION_PATCH, return_value=session):
            validate_credentials("token", "www.wrike.com")
        called_url = session.get.call_args.args[0]
        assert called_url == "https://www.wrike.com/api/v4/contacts?me=true"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_single_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"kind": "contacts", "data": [{"id": "a"}, {"id": "b"}]})])
        manager = _make_manager()

        rows = _rows(_source("contacts", manager=manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginated_endpoint_follows_next_page_token(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"data": [{"id": 1}], "nextPageToken": "tok2"}),
                _response({"data": [{"id": 2}]}),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("tasks", manager=manager))

        assert rows == [{"id": 1}, {"id": 2}]
        # First request carries pageSize; second carries the resume token.
        assert params[0]["pageSize"] == 1000
        assert "nextPageToken" not in params[0]
        assert params[1]["nextPageToken"] == "tok2"
        # State saved once, after yielding the first page, before fetching the next.
        manager.save_state.assert_called_once_with(WrikeResumeConfig(next_page_token="tok2"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": 3}]})])
        manager = _make_manager(WrikeResumeConfig(next_page_token="resume_tok"))

        rows = _rows(_source("tasks", manager=manager))

        assert rows == [{"id": 3}]
        assert params[0]["nextPageToken"] == "resume_tok"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_data_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": []})])

        rows = _rows(_source("tasks"))

        assert rows == []

    def test_rejects_non_wrike_host_before_any_request(self) -> None:
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            with pytest.raises(ValueError, match="non-Wrike host"):
                _source("tasks", host="evil.com")
        MockSession.assert_not_called()


class TestWrikeSource:
    def test_tasks_partition_on_created_date(self) -> None:
        response = _source("tasks")
        assert response.name == "tasks"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdDate"]

    @pytest.mark.parametrize("endpoint", ["folders", "contacts", "workflows", "custom_fields", "spaces"])
    def test_unpartitioned_endpoints(self, endpoint: str) -> None:
        response = _source(endpoint)
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
