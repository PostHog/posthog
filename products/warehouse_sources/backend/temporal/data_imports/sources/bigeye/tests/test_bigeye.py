import json
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye import bigeye as bigeye_module
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.bigeye import (
    BigeyeResumeConfig,
    _auth_header_value,
    _base_url,
    _flatten_collection,
    bigeye_source,
    get_resource,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.settings import (
    BIGEYE_ENDPOINTS,
    REQUEST_TIMEOUT_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the bigeye module.
BIGEYE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.bigeye.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BigeyeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT PREPARE TIME.

    ``request.params`` / ``request.json`` are single dicts mutated in place across pages, so
    inspecting them after the run shows only the final state — snapshot copies when each request
    is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "method": request.method,
                "url": request.url,
                "params": dict(request.params or {}),
                "json": dict(request.json) if request.json is not None else None,
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _build(endpoint: str, manager: mock.MagicMock, host: str | None = None, workspace_id: int | None = None) -> Any:
    return bigeye_source(
        api_key="key",
        host=host,
        workspace_id=workspace_id,
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestNormalizeHost:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "app.bigeye.com"),
            ("", "app.bigeye.com"),
            ("   ", "app.bigeye.com"),
            ("app.bigeye.com", "app.bigeye.com"),
            ("https://app.bigeye.com", "app.bigeye.com"),
            ("https://app.bigeye.com/", "app.bigeye.com"),
            ("http://bigeye.internal.example.com/api", "bigeye.internal.example.com"),
        ],
    )
    def test_normalizes(self, value: str | None, expected: str) -> None:
        assert normalize_host(value) == expected

    def test_base_url_defaults_to_saas_host(self) -> None:
        assert _base_url(None) == "https://app.bigeye.com"

    def test_base_url_honors_custom_host(self) -> None:
        assert _base_url("bigeye.internal.example.com") == "https://bigeye.internal.example.com"


class TestFlattenCollection:
    def test_copies_id_and_name_to_root(self) -> None:
        item = {"collectionConfiguration": {"id": 42, "name": "Nightly checks"}, "collectionMetricStatus": {}}
        flattened = _flatten_collection(item)
        assert flattened["id"] == 42
        assert flattened["name"] == "Nightly checks"
        assert flattened["collectionConfiguration"] == {"id": 42, "name": "Nightly checks"}

    def test_missing_configuration_does_not_raise(self) -> None:
        assert _flatten_collection({}) == {"id": None, "name": None}


class TestGetResource:
    @pytest.mark.parametrize("name", list(BIGEYE_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_resource(self, name: str) -> None:
        resource = cast(dict[str, Any], get_resource(name, workspace_id=None))
        assert resource["name"] == name
        assert resource["endpoint"]["path"] == BIGEYE_ENDPOINTS[name].path

    def test_paginated_endpoint_omits_workspace_id_when_unset(self) -> None:
        resource = cast(dict[str, Any], get_resource("Sources", workspace_id=None))
        assert resource["endpoint"]["json"] == {"pageSize": 100}

    def test_paginated_endpoint_includes_workspace_id_when_set(self) -> None:
        resource = cast(dict[str, Any], get_resource("Sources", workspace_id=7))
        assert resource["endpoint"]["json"] == {"pageSize": 100, "workspaceId": 7}

    def test_collections_includes_workspace_id_as_query_param(self) -> None:
        resource = cast(dict[str, Any], get_resource("Collections", workspace_id=7))
        assert resource["endpoint"]["params"] == {"workspaceId": 7}

    def test_workspaces_endpoint_has_no_workspace_scoping(self) -> None:
        resource = cast(dict[str, Any], get_resource("Workspaces", workspace_id=7))
        assert "json" not in resource["endpoint"]
        assert "params" not in resource["endpoint"]

    def test_collections_carries_flatten_data_map(self) -> None:
        resource = cast(dict[str, Any], get_resource("Collections", workspace_id=None))
        assert resource["data_map"] is _flatten_collection


class TestSinglePageEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_workspaces_single_get_request(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        calls = _wire(session, [_response({"workspaces": [{"id": 1, "name": "Default"}]})])

        rows = _rows(_build("Workspaces", manager))

        assert [r["id"] for r in rows] == [1]
        assert len(calls) == 1
        assert calls[0]["method"] == "GET"
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metrics_uses_metrics_key(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        _wire(session, [_response({"metrics": [{"id": 5}]})])

        rows = _rows(_build("Metrics", manager))

        assert [r["id"] for r in rows] == [5]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_collections_flattens_nested_id(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        _wire(
            session,
            [_response({"collectionInfos": [{"collectionConfiguration": {"id": 9, "name": "Nightly"}}]})],
        )

        rows = _rows(_build("Collections", manager))

        assert rows[0]["id"] == 9
        assert rows[0]["name"] == "Nightly"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_bounds_every_request_with_a_timeout(self, MockSession: mock.MagicMock) -> None:
        # Without this a stalled connect or hung read on a customer-controlled host would pin an
        # import worker indefinitely.
        session = MockSession.return_value
        manager = _make_manager()
        _wire(session, [_response({"workspaces": [{"id": 1, "name": "Default"}]})])

        _rows(_build("Workspaces", manager))

        assert session.send.call_args.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_never_follows_redirects(self, MockSession: mock.MagicMock) -> None:
        # A validated host could still 3xx a sync request to an internal address; refuse to
        # follow redirects on every sync request (SSRF defense-in-depth).
        session = MockSession.return_value
        manager = _make_manager()
        _wire(session, [_response({"workspaces": [{"id": 1, "name": "Default"}]})])

        _rows(_build("Workspaces", manager))

        assert session.send.call_args.kwargs["allow_redirects"] is False


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pages_until_cursor_empty(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        calls = _wire(
            session,
            [
                _response({"sources": [{"id": 1}], "paginationInfo": {"nextCursor": "c1"}}),
                _response({"sources": [{"id": 2}], "paginationInfo": {"nextCursor": ""}}),
            ],
        )

        rows = _rows(_build("Sources", manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert [c["method"] for c in calls] == ["POST", "POST"]
        assert calls[0]["json"] == {"pageSize": 100}
        assert calls[1]["json"] == {"pageSize": 100, "pageCursor": "c1"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_issues_uses_singular_issue_key(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        _wire(session, [_response({"issue": [{"id": 3}], "paginationInfo": {"nextCursor": ""}})])

        rows = _rows(_build("Issues", manager))

        assert [r["id"] for r in rows] == [3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_cursor_after_non_terminal_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        _wire(
            session,
            [
                _response({"tables": [{"id": 1}], "paginationInfo": {"nextCursor": "c1"}}),
                _response({"tables": [{"id": 2}], "paginationInfo": {"nextCursor": ""}}),
            ],
        )

        _rows(_build("Tables", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [BigeyeResumeConfig(next_cursor="c1")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_terminal_page_saves_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        _wire(session, [_response({"tables": [{"id": 1}], "paginationInfo": {"nextCursor": ""}})])

        _rows(_build("Tables", manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        manager = _make_manager(BigeyeResumeConfig(next_cursor="resumed"))
        calls = _wire(session, [_response({"tables": [{"id": 1}], "paginationInfo": {"nextCursor": ""}})])

        _rows(_build("Tables", manager))

        assert calls[0]["json"] == {"pageSize": 100, "pageCursor": "resumed"}


class TestBigeyeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(BIGEYE_ENDPOINTS.keys()))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_match_settings(self, MockSession: mock.MagicMock, endpoint: str) -> None:
        MockSession.return_value.headers = {}
        response = _build(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == [BIGEYE_ENDPOINTS[endpoint].primary_key]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_items_is_lazy(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.headers = {}
        _build("Workspaces", _make_manager())
        session.send.assert_not_called()

    def test_auth_header_carries_apikey_prefix(self) -> None:
        # Bigeye's auth header is `apikey <token>`, not the framework's default `Bearer <token>`.
        assert _auth_header_value("secret-token") == "apikey secret-token"


class TestValidateCredentials:
    def _run(self, response: Any, **kwargs: Any) -> tuple[bool, str | None]:
        with mock.patch(BIGEYE_SESSION_PATCH) as factory:
            session = factory.return_value
            session.get.return_value = response
            return validate_credentials(api_key="key", host=None, workspace_id=None, **kwargs)

    def test_ok(self) -> None:
        valid, error = self._run(_response({"workspaces": []}, status_code=200))
        assert valid is True
        assert error is None

    def test_invalid_api_key(self) -> None:
        valid, error = self._run(_response({}, status_code=401))
        assert valid is False
        assert error == "Invalid Bigeye API key. Please check your key and try again."

    def test_forbidden(self) -> None:
        valid, error = self._run(_response({}, status_code=403))
        assert valid is False
        assert error is not None and "permission" in error

    def test_unexpected_status(self) -> None:
        valid, error = self._run(_response({}, status_code=500))
        assert valid is False
        assert error is not None and "500" in error

    def test_network_error_returns_message(self) -> None:
        with mock.patch(BIGEYE_SESSION_PATCH) as factory:
            factory.return_value.get.side_effect = requests.ConnectionError("boom")
            valid, error = validate_credentials(api_key="key", host=None, workspace_id=None)
        assert valid is False
        assert error is not None and "boom" in error

    def test_rejects_redirect_response(self) -> None:
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with mock.patch(BIGEYE_SESSION_PATCH) as factory:
            resp = _response({}, status_code=302)
            resp.headers["Location"] = "https://10.0.0.1/internal"
            factory.return_value.get.return_value = resp
            valid, error = validate_credentials(api_key="key", host=None, workspace_id=None)
        assert valid is False
        assert error == "That Bigeye host is not allowed."
        assert factory.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host_when_team_id_supplied(self) -> None:
        # When a team_id is supplied, a host resolving to an internal address is rejected before
        # any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(bigeye_module, "_is_host_safe", return_value=(False, "internal address")),
            mock.patch(BIGEYE_SESSION_PATCH) as factory,
        ):
            valid, error = validate_credentials(api_key="key", host="10.0.0.1", workspace_id=None, team_id=99)

        assert valid is False
        assert error == "internal address"
        factory.return_value.get.assert_not_called()

    def test_custom_host_is_used(self) -> None:
        with mock.patch(BIGEYE_SESSION_PATCH) as factory:
            factory.return_value.get.return_value = _response({"workspaces": []}, status_code=200)
            validate_credentials(api_key="key", host="bigeye.internal.example.com", workspace_id=None)

        called_url = factory.return_value.get.call_args.args[0]
        assert called_url == "https://bigeye.internal.example.com/api/v1/workspaces"
