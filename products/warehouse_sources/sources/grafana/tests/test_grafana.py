import json
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.grafana import (
    GrafanaAuthMethodConfig,
    GrafanaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana import grafana as grafana_module
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.grafana import (
    ANNOTATIONS_LIMIT,
    BASIC_AUTH,
    DASHBOARD_VERSIONS_PAGE_SIZE,
    MAX_RESPONSE_BYTES,
    TOKEN_AUTH,
    GrafanaAuth,
    GrafanaAuthError,
    GrafanaResponseTooLargeError,
    GrafanaResumeConfig,
    _extract_items,
    _permission_error_from_response,
    _read_body_bounded,
    _resolve_auth_headers,
    get_endpoint_permissions,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.settings import (
    DEFAULT_PAGE_SIZE,
    LIBRARY_ELEMENTS_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source import GrafanaSource


def _response(
    *,
    status_code: int = 200,
    json_data: Any = None,
    text: str = "",
    headers: dict[str, str] | None = None,
    body_chunks: list[bytes] | None = None,
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    # The source reads bodies via response.iter_content (stream=True), not response.json().
    if body_chunks is not None:
        chunks = body_chunks
    elif json_data is not None:
        chunks = [json.dumps(json_data).encode()]
    elif text:
        chunks = [text.encode()]
    else:
        chunks = []
    response.iter_content.return_value = chunks
    response.headers = headers or {}
    # Responses are consumed inside a `with` block, so the mock must behave as a context manager.
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _token_auth() -> GrafanaAuth:
    return GrafanaAuth(method=TOKEN_AUTH, token="glsa_secret")


def _basic_auth() -> GrafanaAuth:
    return GrafanaAuth(method=BASIC_AUTH, username="admin", password="hunter2")


def _driver() -> SourceDriver:
    return SourceDriver(
        GrafanaSource(),
        GrafanaSourceConfig(
            host="https://x.grafana.net",
            auth_method=GrafanaAuthMethodConfig(selection="token", token="glsa_secret"),
        ),
    )


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://yourstack.grafana.net", "https://yourstack.grafana.net"),
            ("yourstack.grafana.net", "https://yourstack.grafana.net"),
            ("https://yourstack.grafana.net/", "https://yourstack.grafana.net"),
            ("https://yourstack.grafana.net/api", "https://yourstack.grafana.net"),
            ("  yourstack.grafana.net  ", "https://yourstack.grafana.net"),
            ("http://localhost:3000", "http://localhost:3000"),
            ("http://127.0.0.1:3000", "http://127.0.0.1:3000"),
            # Plaintext HTTP to a remote host is upgraded to HTTPS so credentials aren't sent in the clear.
            ("http://grafana.mycompany.com", "https://grafana.mycompany.com"),
            ("HTTP://grafana.mycompany.com/api", "https://grafana.mycompany.com"),
            # URL-embedded credentials are stripped so they're never persisted or sent.
            ("https://admin:hunter2@grafana.mycompany.com", "https://grafana.mycompany.com"),
            ("https://admin:hunter2@grafana.mycompany.com:3000/api", "https://grafana.mycompany.com:3000"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestResolveAuthHeaders:
    def test_basic_auth_sends_base64_credentials(self):
        headers = _resolve_auth_headers(_basic_auth())
        # base64("admin:hunter2")
        assert headers["Authorization"] == "Basic YWRtaW46aHVudGVyMg=="

    def test_org_id_header_set_when_provided(self):
        headers = _resolve_auth_headers(_token_auth(), org_id="2")
        assert headers["X-Grafana-Org-Id"] == "2"

    @pytest.mark.parametrize(
        "auth",
        [
            GrafanaAuth(method=TOKEN_AUTH, token=None),
            GrafanaAuth(method=BASIC_AUTH, username="admin", password=None),
            GrafanaAuth(method=BASIC_AUTH, username=None, password="pw"),
        ],
    )
    def test_missing_credentials_raise_auth_error(self, auth):
        with pytest.raises(GrafanaAuthError):
            _resolve_auth_headers(auth)


class TestExtractItems:
    @pytest.mark.parametrize(
        "data, data_key, expected",
        [
            ([{"id": 1}, {"id": 2}], None, [{"id": 1}, {"id": 2}]),
            ([{"id": 1}, "skip-me", 5], None, [{"id": 1}]),
            ({"teams": [{"id": 1}], "totalCount": 1}, "teams", [{"id": 1}]),
            ({"totalCount": 0}, "teams", []),
            (None, None, []),
            ("nonsense", None, []),
            ({"teams": "nonsense"}, "teams", []),
            ({"result": {"elements": [{"uid": "p1"}], "totalCount": 1}}, "result.elements", [{"uid": "p1"}]),
            ({"result": None}, "result.elements", []),
            ({"result": [{"uid": "p1"}]}, "result.elements", []),
        ],
    )
    def test_extract_items(self, data, data_key, expected):
        assert _extract_items(data, data_key) == expected


class TestBoundedResponseReading:
    def test_streamed_body_over_limit_raises(self):
        # A host with no (or a lying) Content-Length can still stream an unbounded body; the running
        # byte total must abort the read rather than buffer it all into the worker.
        oversized = [b"x" * (1024 * 1024)] * (MAX_RESPONSE_BYTES // (1024 * 1024) + 1)
        response = _response(body_chunks=oversized)
        with pytest.raises(GrafanaResponseTooLargeError):
            _read_body_bounded(response)

    def test_oversized_content_length_rejected_before_reading_body(self):
        response = _response(headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}, body_chunks=[b"ignored"])
        with pytest.raises(GrafanaResponseTooLargeError):
            _read_body_bounded(response)
        response.iter_content.assert_not_called()


class TestPermissionErrorParsing:
    def test_falls_back_to_generic_message(self):
        response = _response(status_code=403, json_data={"message": "Access denied"})
        message = _permission_error_from_response(response)
        assert "permission" in message.lower()
        assert "Access denied" not in message


class TestValidateCredentials:
    def test_invalid_credentials(self):
        with scripted_network([ScriptedResponse(status=401, json={"message": "Unauthorized"})]) as network:
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth())
        assert valid is False
        assert msg == "Invalid Grafana credentials"
        assert network.requests_log[0].path == "/api/org"

    def test_403_passes_at_source_create_but_fails_for_schema(self):
        # An under-scoped (but genuine) token must not block source creation — per-endpoint scope
        # is reported separately — yet must fail a per-schema check.
        response = ScriptedResponse(
            status=403, json={"message": "You'll need additional permissions. Permissions needed: orgs:read"}
        )
        with scripted_network([response, response]) as network:
            assert validate_credentials("https://x.grafana.net", _token_auth()) == (True, None)
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth(), schema_name="teams")
        assert valid is False
        assert msg is not None and "orgs:read" in msg
        assert [request.path for request in network.requests_log] == ["/api/org", "/api/org"]

    def test_rejects_redirect_response(self):
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/api/org"})]
        ) as network:
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth())
        assert valid is False
        assert msg == grafana_module.HOST_NOT_ALLOWED_ERROR
        assert network.requests_log[0].path == "/api/org"

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(grafana_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", _token_auth(), team_id=99)
        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []

    @pytest.mark.parametrize(
        "host",
        ["https://admin:hunter2@grafana.mycompany.com", "admin:hunter2@grafana.mycompany.com"],
    )
    def test_rejects_url_embedded_credentials(self, host):
        # The host field is stored as non-secret config, so a password embedded in the URL would
        # be exposed to anyone who can view the source configuration.
        with scripted_network([]) as network:
            valid, msg = validate_credentials(host, _token_auth())
        assert valid is False
        assert msg is not None
        assert "hunter2" not in msg
        assert network.requests_log == []

    def test_missing_token_surfaces_before_probe(self):
        with scripted_network([]) as network:
            valid, msg = validate_credentials("https://x.grafana.net", GrafanaAuth(method=TOKEN_AUTH, token=None))
        assert valid is False
        assert msg == "Missing Grafana service account token"
        assert network.requests_log == []

    def test_connection_error_does_not_leak_host(self):
        raw = "HTTPSConnectionPool(host='203.0.113.10', port=443): Max retries exceeded"
        with scripted_network(always(ConnectionResetError(raw))) as network:
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth())
        assert valid is False
        assert msg is not None
        assert "203.0.113.10" not in msg
        assert "HTTPSConnectionPool" not in msg
        assert {request.path for request in network.requests_log} == {"/api/org"}

    def test_unexpected_status_does_not_leak_response_body(self):
        leaked_body = '{"error": "SENTINEL_UPSTREAM_BODY"}'
        with scripted_network([ScriptedResponse(status=404, body=leaked_body.encode())]):
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth())
        assert valid is False
        assert msg is not None
        assert "SENTINEL_UPSTREAM_BODY" not in msg
        assert "404" in msg


class TestGetEndpointPermissions:
    def test_maps_status_codes_to_reasons(self):
        with scripted_network(
            route(
                {
                    "/api/search": [ScriptedResponse(json=[{"uid": "d1"}]), ScriptedResponse(json=[{"uid": "d1"}])],
                    "/api/teams/search": [
                        ScriptedResponse(status=403, json={"message": "Permissions needed: teams:read"}),
                        ScriptedResponse(status=403, json={"message": "Permissions needed: teams:read"}),
                    ],
                    "/api/dashboards/uid/d1/versions": [
                        ScriptedResponse(status=403, json={"message": "Permissions needed: dashboards:write"})
                    ],
                }
            )
        ) as network:
            results = get_endpoint_permissions(
                "https://x.grafana.net",
                _token_auth(),
                None,
                1,
                ["dashboards", "teams", "team_members", "dashboard_versions"],
            )
        assert results["dashboards"] is None
        assert results["teams"] is not None and "teams:read" in results["teams"]
        # A fan-out child is unreachable when its parent is, and otherwise needs its own permission,
        # so it is probed through a real parent id, never through its unresolved `{parent_id}` path.
        assert results["team_members"] == results["teams"]
        assert results["dashboard_versions"] is not None and "dashboards:write" in results["dashboard_versions"]
        assert all("{" not in request.path for request in network.requests_log)

    @pytest.mark.parametrize(
        "endpoint, path, expected_reason",
        [
            # An Enterprise-only API is missing on OSS, so the table picker says why it can't sync.
            ("roles", "/api/access-control/roles", "Roles are only available on Grafana Enterprise and Grafana Cloud."),
            # Other tables keep treating a 404 as reachable rather than as a missing scope.
            ("alert_rules", "/api/v1/provisioning/alert-rules", None),
        ],
    )
    def test_not_found_reason(self, endpoint, path, expected_reason):
        with scripted_network(route({path: [ScriptedResponse(status=404, body=b"not found")]})):
            results = get_endpoint_permissions("https://x.grafana.net", _token_auth(), None, 1, [endpoint])
        assert results == {endpoint: expected_reason}

    def test_network_blip_is_not_a_missing_scope(self):
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            results = get_endpoint_permissions("https://x.grafana.net", _token_auth(), None, 1, ["dashboards"])
        assert results == {"dashboards": None}
        assert {request.path for request in network.requests_log} == {"/api/search"}


class TestPagedRows:
    def test_resumes_from_saved_page(self):
        result = _driver().run(
            "dashboards", [ScriptedResponse(json=[{"uid": "d1"}])], resume_state=GrafanaResumeConfig(next_page=3)
        )
        assert result.raised is None
        assert result.params("page") == ["3"]
        assert result.rows == [{"uid": "d1"}]

    def test_library_elements_walk_nested_pages_at_their_own_page_size(self):
        full_page = [{"uid": f"p{i}"} for i in range(LIBRARY_ELEMENTS_PAGE_SIZE)]
        result = _driver().run(
            "library_elements",
            [
                ScriptedResponse(json={"result": {"elements": full_page, "page": 1}}),
                ScriptedResponse(json={"result": {"elements": [{"uid": "last"}], "page": 2}}),
            ],
        )
        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.params("perPage") == [str(LIBRARY_ELEMENTS_PAGE_SIZE)] * 2
        assert len(result.rows) == LIBRARY_ELEMENTS_PAGE_SIZE + 1

    def test_unpaginated_endpoint_single_request(self):
        result = _driver().run("datasources", [ScriptedResponse(json=[{"uid": "ds1"}, {"uid": "ds2"}])])
        assert result.raised is None
        assert result.items == [[{"uid": "ds1"}, {"uid": "ds2"}]]
        assert len(result.requests) == 1
        assert result.params("page") == [None]

    def test_stops_at_per_run_page_budget(self):
        # A host returning full pages forever must not loop without end; the run stops at the budget
        # and leaves resume state so the next sync continues.
        full_page = [{"uid": f"d{i}"} for i in range(DEFAULT_PAGE_SIZE)]
        with mock.patch.object(grafana_module, "MAX_PAGES_PER_RUN", 3):
            result = _driver().run("dashboards", [ScriptedResponse(json=full_page)] * 6)
        assert result.raised is None
        assert len(result.requests) == 3
        assert result.saved_states[-1].next_page == 4


class TestFanOutRows:
    def test_dashboard_versions_legacy_array_pages_by_offset(self):
        full_page = [{"uid": "d1", "version": v} for v in range(DASHBOARD_VERSIONS_PAGE_SIZE)]
        result = _driver().run(
            "dashboard_versions",
            route(
                {
                    "/api/search": [ScriptedResponse(json=[{"uid": "d1"}])],
                    "/api/dashboards/uid/d1/versions": [
                        ScriptedResponse(json=full_page),
                        ScriptedResponse(json=[{"uid": "d1", "version": 999}]),
                    ],
                }
            ),
        )
        assert result.raised is None
        assert len(result.items) == 2
        assert result.requests[1].param("start") is None
        assert result.requests[2].param("start") == str(DASHBOARD_VERSIONS_PAGE_SIZE)

    def test_skips_parent_deleted_mid_sync(self):
        result = _driver().run(
            "dashboard_versions",
            route(
                {
                    "/api/search": [ScriptedResponse(json=[{"uid": "gone"}, {"uid": "d2"}])],
                    "/api/dashboards/uid/gone/versions": [ScriptedResponse(status=404, body=b"not found")],
                    "/api/dashboards/uid/d2/versions": [
                        ScriptedResponse(json={"versions": [{"version": 1}], "continueToken": ""})
                    ],
                }
            ),
        )
        assert result.raised is None
        assert result.items == [[{"uid": "d2", "version": 1}]]

    @pytest.mark.parametrize(
        "endpoint, parent_path, child_path, parent_key",
        [
            ("dashboard_permissions", "/api/search", "/api/access-control/dashboards/r1", "dashboardUid"),
            ("folder_permissions", "/api/folders", "/api/access-control/folders/r1", "folderUid"),
        ],
    )
    def test_resource_permissions_keyed_by_subject(self, endpoint, parent_path, child_path, parent_key):
        grants = [
            {"id": 0, "userId": 7, "userLogin": "jo", "isInherited": False, "permission": "Edit"},
            {"id": 0, "userId": 7, "userLogin": "jo", "isInherited": True, "permission": "Edit"},
            {"id": 0, "teamId": 3, "team": "ops", "isInherited": True, "permission": "View"},
            {"id": 12, "builtInRole": "Admin", "isInherited": False, "permission": "Admin"},
            # Grafana appends an implicit Admin grant when access control enforcement is off.
            {"builtInRole": "Admin", "isInherited": False, "permission": "Admin"},
            {"id": 0, "roleName": "managed:custom", "permission": "View"},
        ]
        result = _driver().run(
            endpoint,
            route(
                {
                    parent_path: [ScriptedResponse(json=[{"uid": "r1"}])],
                    child_path: [ScriptedResponse(json=grants)],
                }
            ),
        )
        assert result.raised is None
        assert [(row[parent_key], row["subject"], row["isInherited"], row["permission"]) for row in result.rows] == [
            ("r1", "user:7", False, "Edit"),
            ("r1", "user:7", True, "Edit"),
            ("r1", "team:3", True, "View"),
            ("r1", "role:Admin", False, "Admin"),
            ("r1", "role:managed:custom", False, "View"),
        ]

    def test_resumes_from_saved_parent_index(self):
        result = _driver().run(
            "team_members",
            route(
                {
                    "/api/teams/search": [ScriptedResponse(json={"teams": [{"id": 1}, {"id": 2}]})],
                    "/api/teams/2/members": [ScriptedResponse(json=[{"userId": 11}])],
                }
            ),
            resume_state=GrafanaResumeConfig(next_page=2, next_parent_index=1),
        )
        assert result.raised is None
        assert result.requests[0].param("page") == "2"
        assert result.items == [[{"teamId": 2, "userId": 11}]]

    def test_budget_cut_leaves_cursor_on_unfinished_parent(self):
        # A host handing out continue tokens forever must not loop without end, and the parent it
        # cut short must be re-fetched on the next sync rather than skipped.
        endless = [{"versions": [{"version": v}], "continueToken": f"t{v}"} for v in range(10)]
        with mock.patch.object(grafana_module, "MAX_PAGES_PER_RUN", 3):
            result = _driver().run(
                "dashboard_versions",
                route(
                    {
                        "/api/search": [ScriptedResponse(json=[{"uid": "d1"}, {"uid": "d2"}])],
                        "/api/dashboards/uid/d1/versions": [ScriptedResponse(json=page) for page in endless],
                    }
                ),
            )
        assert result.raised is None
        assert len(result.requests) == 3
        assert result.saved_states[-1] == GrafanaResumeConfig(next_page=1, next_parent_index=0)


class TestAnnotationRows:
    def test_saturated_window_bisects_oldest_first(self):
        saturated = [{"id": i, "time": i} for i in range(ANNOTATIONS_LIMIT)]
        left_rows = [{"id": 1, "time": 10}]
        right_rows = [{"id": 2, "time": 20}]
        result = _driver().run(
            "annotations",
            [ScriptedResponse(json=saturated), ScriptedResponse(json=left_rows), ScriptedResponse(json=right_rows)],
        )

        assert result.raised is None
        assert result.items == [left_rows, right_rows]
        calls = [(int(request.param("from") or "0"), int(request.param("to") or "0")) for request in result.requests]
        first_from, first_to = calls[0]
        mid = (first_from + first_to) // 2
        # Halves cover the full original window (sharing the mid boundary) and run oldest-first.
        assert calls[1] == (first_from, mid)
        assert calls[2] == (mid, first_to)
        # After the older half yields, the resume boundary advances to its upper bound.
        assert [state.annotations_from_ms for state in result.saved_states] == [mid]

    def test_resumes_from_saved_boundary(self):
        result = _driver().run(
            "annotations", [ScriptedResponse(json=[])], resume_state=GrafanaResumeConfig(annotations_from_ms=5_000_000)
        )
        assert result.raised is None
        assert result.params("from") == ["5000000"]

    def test_future_watermark_fetches_nothing(self):
        # A watermark at/past "now" leaves no window to walk; the sync must no-op, not error.
        far_future_ms = 4102444800000  # 2100-01-01
        result = _driver().run(
            "annotations",
            [],
            incremental_field="time",
            db_incremental_field_last_value=far_future_ms,
        )
        assert result.raised is None
        assert result.items == []
        assert result.requests == []

    def test_stops_at_per_run_request_budget(self):
        # A host that saturates every window would fan out without end; the run stops at the budget.
        saturated = [{"id": i, "time": i} for i in range(ANNOTATIONS_LIMIT)]

        with mock.patch.object(grafana_module, "MAX_ANNOTATION_REQUESTS_PER_RUN", 3):
            result = _driver().run("annotations", always(ScriptedResponse(json=saturated)))
        assert result.raised is None
        assert len(result.requests) == 3


class TestGrafanaSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, sort_mode",
        [
            ("dashboards", ["uid"], "asc"),
            ("folders", ["uid"], "asc"),
            ("teams", ["id"], "asc"),
            ("users", ["userId"], "asc"),
            ("datasources", ["uid"], "asc"),
            ("service_accounts", ["id"], "asc"),
            ("alert_rules", ["uid"], "asc"),
            ("annotations", ["id"], "desc"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, sort_mode):
        result = _driver().run(endpoint, [ScriptedResponse(json=[] if endpoint != "teams" else {"teams": []})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode


class TestSessionRetriesDisabled:
    # A hostile Grafana host can answer 429/503 with a huge Retry-After. urllib3's default adapter
    # policy honors it and sleeps for hours inside a single session.get, underneath and defeating the
    # bounded response/walk deadlines. Every session must disable adapter retries so _make_fetch's
    # own Tenacity policy (bounded jitter/backoff) is the only retry mechanism.
    @pytest.mark.parametrize(
        "operation",
        [
            "validate_credentials",
            "get_endpoint_permissions",
            "extract_folders",
        ],
    )
    def test_sessions_disable_adapter_retries(self, operation):
        if operation == "extract_folders":
            options = _driver().run("folders", [ScriptedResponse(json=[])]).session_options
        else:
            with scripted_network([ScriptedResponse(json=[])]) as network:
                if operation == "validate_credentials":
                    validate_credentials("https://x.grafana.net", _token_auth())
                else:
                    get_endpoint_permissions("https://x.grafana.net", _token_auth(), None, 1, ["dashboards"])
            options = network.session_options
        assert options
        for kwargs in options:
            retry = kwargs.get("retry")
            assert retry is not None and retry.total == 0
