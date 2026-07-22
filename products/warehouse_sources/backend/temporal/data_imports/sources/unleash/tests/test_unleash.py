import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash import unleash
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.unleash import (
    PAGE_SIZE,
    UnleashHostNotAllowedError,
    UnleashResumeConfig,
    _headers,
    check_endpoint_permissions,
    normalize_instance_url,
    unleash_source,
    validate_credentials,
)

# RESTClient builds its pipeline session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The runtime host-safety guard resolves DNS; patch it so pipeline tests don't hit the network.
IS_HOST_SAFE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.unleash.unleash._is_host_safe"

BASE_URL = "https://unleash.example.com"
TOKEN = "user:secret-token"


def _json_response(body: Any, *, status_code: int = 200, location: Optional[str] = None) -> requests.Response:
    """A real requests.Response so the framework's status/redirect/parse handling behaves as in prod."""
    resp = requests.Response()
    resp.status_code = status_code
    resp.url = f"{BASE_URL}/api/admin/probe"
    resp.reason = "OK" if status_code < 400 else "Error"
    if location is not None:
        resp.headers["Location"] = location
    resp._content = json.dumps(body).encode()
    return resp


def _mock_response(status_code: int = 200, json_data: Any = None, is_redirect: bool = False) -> MagicMock:
    """MagicMock response for the validate_credentials / check_endpoint_permissions probe helpers."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.is_redirect = is_redirect
    response.is_permanent_redirect = False
    response.json.return_value = json_data
    response.text = str(json_data)
    response.raise_for_status.side_effect = (
        requests.HTTPError(f"{status_code} Client Error", response=response) if status_code >= 400 else None
    )
    return response


def _make_manager(resume_state: UnleashResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: MagicMock, endpoint: str, instance_url: str = BASE_URL) -> Any:
    return unleash_source(
        instance_url=instance_url,
        api_token=TOKEN,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestNormalizeAndHeaders:
    @parameterized.expand(
        [
            ("plain", "https://unleash.example.com", "https://unleash.example.com"),
            ("trailing_slash", "https://unleash.example.com/", "https://unleash.example.com"),
            ("api_suffix", "https://unleash.example.com/api", "https://unleash.example.com"),
            ("api_admin_suffix", "https://unleash.example.com/api/admin/", "https://unleash.example.com"),
            ("no_scheme", "unleash.example.com", "https://unleash.example.com"),
            ("whitespace", "  https://unleash.example.com  ", "https://unleash.example.com"),
            (
                # Unleash cloud URLs carry the instance name as a path prefix — it must be preserved.
                "cloud_path_prefix",
                "https://us.app.unleash-hosted.com/my-instance/",
                "https://us.app.unleash-hosted.com/my-instance",
            ),
            (
                "cloud_path_prefix_with_api_suffix",
                "https://us.app.unleash-hosted.com/my-instance/api/admin",
                "https://us.app.unleash-hosted.com/my-instance",
            ),
        ]
    )
    def test_normalize_instance_url(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_instance_url(raw) == expected

    def test_headers_send_raw_token_without_bearer_prefix(self) -> None:
        # The probe helpers (validate/permissions) send the raw token as the whole header value.
        assert _headers(TOKEN)["Authorization"] == TOKEN


class TestPipelineTransport:
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_fetches_once_and_extracts_wrapped_rows(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_json_response({"version": 1, "projects": [{"id": "a"}, {"id": "b"}]})])

        manager = _make_manager()
        rows = _rows(_source(manager, "projects"))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert session.send.call_count == 1
        # No offset/limit for the single-request endpoints.
        assert params[0] == {}
        # The whole collection arrives in one response, so nothing is checkpointed.
        manager.save_state.assert_not_called()

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_bare_array_endpoint_extracts_rows(self, MockSession: Any, _safe: Any) -> None:
        # context_fields returns a bare JSON array (no wrapper object / data_selector).
        session = MockSession.return_value
        _wire(session, [_json_response([{"name": "userId"}, {"name": "email"}])])

        rows = _rows(_source(_make_manager(), "context_fields"))
        assert rows == [{"name": "userId"}, {"name": "email"}]

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_with_no_rows_yields_no_batches(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({"version": 1, "projects": []})])

        # An empty collection must not push an empty batch into the pipeline.
        assert list(_source(_make_manager(), "projects").items()) == []

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_paginated_endpoint_walks_offsets_and_saves_state_after_yield(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        full_page = [{"name": f"flag-{i}"} for i in range(PAGE_SIZE)]
        params = _wire(
            session,
            [
                _json_response({"features": full_page, "total": PAGE_SIZE + 2}),
                _json_response({"features": [{"name": "x"}, {"name": "y"}], "total": PAGE_SIZE + 2}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager, "features"))

        assert len(rows) == PAGE_SIZE + 2
        assert [p["offset"] for p in params] == [0, PAGE_SIZE]
        # Stable ascending sort keeps page boundaries fixed while walking offsets.
        assert all(p["sortBy"] == "createdAt" and p["sortOrder"] == "asc" and p["limit"] == PAGE_SIZE for p in params)
        # State is saved once — after the first (full) page, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == UnleashResumeConfig(offset=PAGE_SIZE)

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_paginated_endpoint_stops_on_short_page_without_total(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({"features": [{"name": "only"}]})])

        manager = _make_manager()
        rows = _rows(_source(manager, "features"))
        assert rows == [{"name": "only"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_paginated_endpoint_stops_when_total_reached_on_full_page(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        full_page = [{"name": f"flag-{i}"} for i in range(PAGE_SIZE)]
        _wire(session, [_json_response({"features": full_page, "total": PAGE_SIZE})])

        manager = _make_manager()
        rows = _rows(_source(manager, "features"))
        assert len(rows) == PAGE_SIZE
        # total == offset means the collection is exhausted — no extra empty-page request.
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_paginated_endpoint_resumes_from_saved_offset(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_json_response({"features": [{"name": "x"}], "total": PAGE_SIZE + 1})])

        manager = _make_manager(UnleashResumeConfig(offset=PAGE_SIZE))
        rows = _rows(_source(manager, "features"))
        assert rows == [{"name": "x"}]
        assert [p["offset"] for p in params] == [PAGE_SIZE]

    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_token_travels_via_raw_api_key_auth_not_plain_headers(self, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        session.headers = {}
        captured_auth: list[Any] = []

        def _prepare(request: Any) -> MagicMock:
            captured_auth.append(request.auth)
            prepared = MagicMock()
            prepared.url = request.url
            return prepared

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_json_response({"version": 1, "projects": [{"id": "a"}]})]

        _rows(_source(_make_manager(), "projects"))

        # The raw token (no Bearer prefix) rides in the Authorization header via redacting auth.
        assert captured_auth[0].api_key == TOKEN
        assert captured_auth[0].name == "Authorization"
        assert captured_auth[0].location == "header"
        assert session.headers.get("Accept") == "application/json"
        assert "Authorization" not in session.headers

    def test_blocks_unsafe_hosts(self) -> None:
        with patch(IS_HOST_SAFE_PATCH, return_value=(False, "blocked")):
            with pytest.raises(UnleashHostNotAllowedError):
                _rows(_source(_make_manager(), "projects", instance_url="https://10.0.0.1"))

    def test_blocks_ambiguous_url(self) -> None:
        with pytest.raises(UnleashHostNotAllowedError):
            _rows(_source(_make_manager(), "projects", instance_url="https://169.254.169.254\\@unleash.example.com"))

    @parameterized.expand(
        [
            ("features", ["name"]),
            # A tag has no id — its identity is the (type, value) pair; a single-column key here
            # would seed duplicate rows and multi-match on every merge.
            ("tags", ["type", "value"]),
        ]
    )
    def test_source_returns_declared_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = _source(_make_manager(), endpoint)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("unavailable", 503)])
    @patch("tenacity.nap.time.sleep")
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_succeed(
        self, _name: str, status: int, MockSession: Any, _safe: Any, _sleep: Any
    ) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_json_response({}, status_code=status), _json_response({"version": 1, "projects": [{"id": "a"}]})],
        )

        rows = _rows(_source(_make_manager(), "projects"))
        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @patch("tenacity.nap.time.sleep")
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_persistent_server_error_exhausts_retries(self, MockSession: Any, _safe: Any, _sleep: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({}, status_code=500)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager(), "projects"))
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_permanent_statuses_raise_http_error(self, _name: str, status: int, MockSession: Any, _safe: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({"message": "no"}, status_code=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager(), "projects"))

    @parameterized.expand([("moved", 301), ("found", 302), ("temporary", 307)])
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_redirects_are_refused(self, _name: str, status: int, MockSession: Any, _safe: Any) -> None:
        # The session never follows redirects — a 3xx would move the sync off the validated host
        # (SSRF), so it must fail rather than be treated as an empty page.
        session = MockSession.return_value
        _wire(session, [_json_response({}, status_code=status, location="https://evil.example.com")])

        with pytest.raises(ValueError, match="[Rr]edirect"):
            _rows(_source(_make_manager(), "projects"))

    @parameterized.expand(
        [
            # A 200 whose body isn't the expected list shape is treated as a transient glitch and
            # retried (the retryable counterpart of the old _extract_rows guard).
            ("wrapped_missing_key", "projects", {"version": 1}),
            ("wrapped_got_array", "projects", [{"id": "a"}]),
            ("bare_got_object", "context_fields", {"fields": []}),
        ]
    )
    @patch("tenacity.nap.time.sleep")
    @patch(IS_HOST_SAFE_PATCH, return_value=(True, None))
    @patch(CLIENT_SESSION_PATCH)
    def test_unexpected_200_body_shape_is_retried_then_raises(
        self, _name: str, endpoint: str, body: Any, MockSession: Any, _safe: Any, _sleep: Any
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response(body)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager(), endpoint))
        assert session.send.call_count == 5


class TestValidateCredentials:
    def _validate(self, monkeypatch: Any, response: MagicMock, schema_name: Optional[str] = None) -> tuple:
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (True, None))
        return validate_credentials(BASE_URL, TOKEN, schema_name=schema_name, team_id=1)

    def test_validate_credentials_success(self, monkeypatch: Any) -> None:
        assert self._validate(monkeypatch, _mock_response(200, {"projects": []})) == (True, None)

    def test_validate_credentials_invalid_token(self, monkeypatch: Any) -> None:
        valid, message = self._validate(monkeypatch, _mock_response(401, {"message": "nope"}))
        assert valid is False
        assert message == "Invalid Unleash API token"

    def test_validate_credentials_accepts_403_at_source_create(self, monkeypatch: Any) -> None:
        # A valid token may lack the permission for the probe endpoint; source creation must
        # still go through, and per-schema syncs surface their own permission errors.
        assert self._validate(monkeypatch, _mock_response(403, {"message": "denied"})) == (True, None)

    def test_validate_credentials_rejects_403_for_scoped_probe(self, monkeypatch: Any) -> None:
        valid, message = self._validate(monkeypatch, _mock_response(403, {"message": "denied"}), schema_name="users")
        assert valid is False
        assert message == "denied"

    def test_validate_credentials_rejects_redirects(self, monkeypatch: Any) -> None:
        # A redirect could bounce the probe to an internal address, defeating the host check.
        valid, _ = self._validate(monkeypatch, _mock_response(200, {}, is_redirect=True))
        assert valid is False

    def test_validate_credentials_rejects_unsafe_host(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        valid, message = validate_credentials("https://10.0.0.1", TOKEN, team_id=1)
        assert valid is False
        assert message == "blocked"

    @parameterized.expand(
        [
            ("blank", "   "),
            ("bad_scheme", "ftp://unleash.example.com"),
            # Parser-differential SSRF guards: urlparse and urllib3 disagree on where the
            # authority ends for backslash/userinfo URLs, so validation could approve one host
            # while requests connects to another.
            ("userinfo", "https://169.254.169.254@unleash.example.com"),
            ("backslash", "https://169.254.169.254\\@unleash.example.com"),
            ("encoded_backslash", "https://169.254.169.254%5C@unleash.example.com"),
        ]
    )
    def test_validate_credentials_rejects_malformed_or_ambiguous_urls(self, _name: str, raw_url: str) -> None:
        valid, message = validate_credentials(raw_url, TOKEN, team_id=1)
        assert valid is False
        assert message == "Invalid Unleash instance URL"

    def test_validate_credentials_handles_connection_errors(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (True, None))
        valid, message = validate_credentials(BASE_URL, TOKEN, team_id=1)
        assert valid is False
        assert message is not None and "Could not connect to Unleash" in message

    @parameterized.expand(
        [
            # The token rides in the Authorization header, so plaintext http is rejected on cloud
            # (public egress) but allowed off cloud (self-hosted controls its own network path).
            ("http_on_cloud", True, "http://unleash.example.com", None),
            ("http_off_cloud", False, "http://unleash.example.com", "unleash.example.com"),
            ("https_on_cloud", True, "https://unleash.example.com", "unleash.example.com"),
        ]
    )
    def test_validated_hostname_requires_https_only_on_cloud(
        self, _name: str, cloud: bool, url: str, expected: Optional[str]
    ) -> None:
        with patch.object(unleash, "is_cloud", return_value=cloud):
            assert unleash._validated_hostname(url) == expected


class TestCheckEndpointPermissions:
    def test_flags_admin_gated_tables(self, monkeypatch: Any) -> None:
        def get(url: str, params: Any = None, **kwargs: Any) -> MagicMock:
            if url.endswith("/api/admin/user-admin"):
                return _mock_response(403, {"message": "You need the ADMIN permission."})
            return _mock_response(200, {"projects": [], "features": [], "total": 0})

        session = MagicMock()
        session.get.side_effect = get
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (True, None))

        result = check_endpoint_permissions(BASE_URL, TOKEN, ["projects", "features", "users"], team_id=1)
        assert result["projects"] is None
        assert result["features"] is None
        assert result["users"] is not None and "Admin root role" in result["users"]

    @parameterized.expand(
        [
            # Transient failures are not permission problems — they must not flag the table.
            ("server_error", 500, None),
            ("throttled", 429, None),
            ("invalid_token", 401, "Invalid Unleash API token"),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: Optional[str]) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code, {})
        with (
            patch.object(unleash, "make_tracked_session", lambda **kwargs: session),
            patch.object(unleash, "_is_host_safe", lambda host, team_id: (True, None)),
        ):
            result = check_endpoint_permissions(BASE_URL, TOKEN, ["projects"], team_id=1)
        assert result["projects"] == expected

    def test_treats_network_blips_as_reachable(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (True, None))
        assert check_endpoint_permissions(BASE_URL, TOKEN, ["projects"], team_id=1) == {"projects": None}

    def test_blocks_unsafe_host_for_all_endpoints(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        result = check_endpoint_permissions("https://10.0.0.1", TOKEN, ["projects", "users"], team_id=1)
        assert result == {"projects": "blocked", "users": "blocked"}

    def test_rejects_ambiguous_url_for_all_endpoints(self) -> None:
        result = check_endpoint_permissions(
            "https://169.254.169.254\\@unleash.example.com", TOKEN, ["projects", "users"], team_id=1
        )
        assert result == {"projects": "Invalid Unleash instance URL", "users": "Invalid Unleash instance URL"}
