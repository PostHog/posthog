import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import ConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify import (
    AUDIT_EVENTS_FORBIDDEN_ERROR,
    AuditEventsPaginationTruncatedError,
    CoolifyHostNotAllowedError,
    DeploymentsPaginationTruncatedError,
    _client_config,
    _DeploymentsPaginator,
    api_base_url,
    coolify_source,
    hostname_of,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.settings import (
    COOLIFY_ENDPOINTS,
    DEPLOYMENTS_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.source import CoolifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coolify import (
    CoolifySourceConfig,
)

BASE_URL = "https://coolify.example.com"
API_BASE = f"{BASE_URL}/api/v1"
APP_UUID = "o8g80wkc4s0gks0k0ok8cog4"


def _driver(base_url: str = BASE_URL) -> SourceDriver:
    return SourceDriver(CoolifySource(), CoolifySourceConfig(base_url=base_url, api_token="coolify-token"))


class TestCoolifyNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            pytest.param("https://coolify.example.com", BASE_URL, id="already_normalized"),
            pytest.param("https://coolify.example.com/", BASE_URL, id="trailing_slash"),
            pytest.param("https://coolify.example.com/api/v1", BASE_URL, id="pasted_api_base"),
            pytest.param("https://coolify.example.com/api/v1/", BASE_URL, id="pasted_api_base_with_slash"),
            pytest.param("coolify.example.com", BASE_URL, id="bare_host_gets_https"),
            pytest.param("  https://coolify.example.com  ", BASE_URL, id="surrounding_whitespace"),
        ],
    )
    def test_resolves_pasted_variants_to_one_instance_root(self, raw: str, expected: str) -> None:
        # Users paste the URL from a browser bar or the API docs; every variant must produce the
        # same request URLs or a pasted `/api/v1` suffix silently doubles into `/api/v1/api/v1`.
        assert normalize_base_url(raw) == expected
        assert api_base_url(raw) == f"{expected}/api/v1"


class TestCoolifyHostnameValidation:
    @pytest.mark.parametrize(
        "url",
        [
            pytest.param("https://127.0.0.1\\@coolify.example.com", id="backslash_authority_smuggling"),
            pytest.param("https://127.0.0.1%5C@coolify.example.com", id="encoded_backslash"),
            pytest.param("https://user@coolify.example.com", id="userinfo"),
            pytest.param("ftp://coolify.example.com", id="non_http_scheme"),
            pytest.param("https://", id="no_host"),
            pytest.param("", id="empty"),
        ],
    )
    def test_rejects_ambiguous_or_malformed_urls(self, url: str) -> None:
        # urlparse and requests disagree on where the authority ends for these shapes, so a URL
        # that validates as one host but connects to another must be rejected outright (SSRF).
        assert hostname_of(url) is None

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify.is_cloud",
        return_value=True,
    )
    def test_rejects_plain_http_on_cloud(self, _mock: MagicMock) -> None:
        # On cloud the bearer token would ride in cleartext to a customer-supplied http host.
        assert hostname_of("http://coolify.example.com") is None

    def test_source_refuses_a_rejected_host(self) -> None:
        with pytest.raises(CoolifyHostNotAllowedError):
            coolify_source("https://user@coolify.example.com", "coolify-token", "servers", team_id=1, job_id="job-1")


class TestCoolifyClientConfig:
    @pytest.mark.parametrize(
        "endpoint,capture_disabled",
        [
            pytest.param("applications", True, id="webhook_secrets_in_the_response"),
            pytest.param("databases", True, id="database_credentials_in_the_response"),
            pytest.param("deployments", True, id="deploy_logs_in_the_response"),
            pytest.param("servers", True, id="log_drain_keys_in_the_response"),
            pytest.param("services", True, id="compose_contents_in_the_response"),
            pytest.param("teams", True, id="member_emails_in_the_response"),
            pytest.param("audit_events", True, id="change_diffs_in_the_response"),
            pytest.param("application_task_executions", True, id="command_output_in_the_response"),
            pytest.param("backup_executions", True, id="raw_backup_configs_in_the_walk"),
            pytest.param("projects", False, id="nothing_to_withhold"),
            pytest.param("project_environments", False, id="environments_nothing_to_withhold"),
        ],
    )
    def test_capture_is_disabled_only_where_the_response_must_not_be_sampled(
        self, endpoint: str, capture_disabled: bool
    ) -> None:
        # Sample capture records the raw response before resource maps run, so stripping a field
        # from storage does not keep it out of a sample; those endpoints must turn capture off,
        # and every other endpoint must leave the operator-configured default in place.
        client_config = _client_config(BASE_URL, "coolify-token", COOLIFY_ENDPOINTS[endpoint])
        if capture_disabled:
            assert client_config["capture"] is False
        else:
            assert "capture" not in client_config


class TestCoolifyFlatEndpoints:
    def test_reads_the_bare_array_from_the_versioned_path(self) -> None:
        # Coolify list endpoints answer a bare JSON array under /api/v1; a wrong data_selector or
        # a doubled/missing API prefix would sync zero rows without erroring.
        result = _driver(base_url=f"{BASE_URL}/api/v1").run(
            "servers", [ScriptedResponse(json=[{"uuid": "srv-1", "name": "hetzner-1"}])]
        )

        assert result.raised is None
        assert result.rows == [{"uuid": "srv-1", "name": "hetzner-1"}]
        assert result.urls == [f"{API_BASE}/servers"]


class TestCoolifyDeploymentsFanout:
    def test_an_application_deleted_mid_sync_does_not_fail_the_table(self) -> None:
        # An app removed between the parent listing and its child fetch answers 404; one such app
        # must cost only its own rows, not the whole deployments table.
        gone_uuid = "gone0000000000000000000000"
        result = _driver().run(
            "deployments",
            [
                ScriptedResponse(json=[{"uuid": uuid, "name": f"app-{uuid}"} for uuid in [gone_uuid, APP_UUID]]),
                ScriptedResponse(status=404, json={}),
                ScriptedResponse(json={"count": 1, "deployments": [{"deployment_uuid": "dep-1"}]}),
            ],
        )

        assert result.raised is None
        assert [row["deployment_uuid"] for row in result.rows] == ["dep-1"]
        assert result.paths == [
            "/api/v1/applications",
            f"/api/v1/deployments/applications/{gone_uuid}",
            f"/api/v1/deployments/applications/{APP_UUID}",
        ]

    def test_a_count_past_the_safety_cap_fails_the_table_instead_of_truncating_it(self) -> None:
        # The deployments table replaces on every sync (`write_disposition: "replace"`). Stopping
        # at the safety cap while `count` still claims more rows exist would silently swap a
        # complete table for an incomplete one; it must raise instead.
        page = [{"deployment_uuid": f"dep-{i}"} for i in range(DEPLOYMENTS_PAGE_SIZE)]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify.MAX_DEPLOYMENTS_OFFSET",
            DEPLOYMENTS_PAGE_SIZE,
        ):
            result = _driver().run(
                "deployments",
                [
                    ScriptedResponse(json=[{"uuid": APP_UUID}]),
                    ScriptedResponse(json={"count": DEPLOYMENTS_PAGE_SIZE + 1, "deployments": page}),
                ],
            )

        assert isinstance(result.raised, DeploymentsPaginationTruncatedError)
        assert result.paths == ["/api/v1/applications", f"/api/v1/deployments/applications/{APP_UUID}"]
        assert result.params("skip") == [None, "0"]

    def test_an_unparseable_body_at_the_cap_stops_without_crashing(self) -> None:
        # If the response at the cap boundary isn't valid JSON, `_DeploymentsPaginator` can't read
        # `count` to tell whether rows were left unfetched; it must fall back to stopping quietly
        # rather than raising on a body it can't interpret.
        paginator = _DeploymentsPaginator(
            limit=DEPLOYMENTS_PAGE_SIZE,
            offset_param="skip",
            limit_param="take",
            total_path="count",
            maximum_offset=DEPLOYMENTS_PAGE_SIZE,
        )
        paginator.offset = DEPLOYMENTS_PAGE_SIZE
        response = Response()
        response.status_code = 200
        response._content = b"not json"
        page = [{"deployment_uuid": f"dep-{i}"} for i in range(DEPLOYMENTS_PAGE_SIZE)]

        paginator.update_state(response, page)

        assert paginator.has_next_page is False


class TestCoolifyNestedFanout:
    @pytest.mark.parametrize(
        "endpoint,responses,expected_paths,expected_rows",
        [
            pytest.param(
                "project_environments",
                [
                    ScriptedResponse(json=[{"uuid": "prj-gone"}, {"uuid": "prj-1"}]),
                    ScriptedResponse(status=404, json={}),
                    ScriptedResponse(json=[{"id": 7, "uuid": "env-1", "name": "production"}]),
                ],
                [
                    "/api/v1/projects",
                    "/api/v1/projects/prj-gone/environments",
                    "/api/v1/projects/prj-1/environments",
                ],
                [{"id": 7, "uuid": "env-1", "name": "production", "project_uuid": "prj-1"}],
                id="project_environments",
            ),
            pytest.param(
                "application_task_executions",
                [
                    ScriptedResponse(json=[{"uuid": "app-gone"}, {"uuid": APP_UUID}]),
                    ScriptedResponse(status=404, json={}),
                    ScriptedResponse(json=[{"uuid": "task-1", "name": "nightly", "command": "secret-cmd"}]),
                    ScriptedResponse(json=[{"uuid": "exe-1", "status": "failed", "message": "token=abc"}]),
                ],
                [
                    "/api/v1/applications",
                    "/api/v1/applications/app-gone/scheduled-tasks",
                    f"/api/v1/applications/{APP_UUID}/scheduled-tasks",
                    f"/api/v1/applications/{APP_UUID}/scheduled-tasks/task-1/executions",
                ],
                [
                    {
                        "uuid": "exe-1",
                        "status": "failed",
                        "task_uuid": "task-1",
                        "task_name": "nightly",
                        "application_uuid": APP_UUID,
                    }
                ],
                id="application_task_executions",
            ),
            pytest.param(
                "backup_executions",
                [
                    ScriptedResponse(json=[{"uuid": "db-1"}]),
                    ScriptedResponse(json=[{"uuid": "bkp-1", "executions": [{"uuid": "embedded"}]}]),
                    ScriptedResponse(json={"executions": [{"uuid": "bex-1", "status": "success", "size": 42}]}),
                ],
                [
                    "/api/v1/databases",
                    "/api/v1/databases/db-1/backups",
                    "/api/v1/databases/db-1/backups/bkp-1/executions",
                ],
                [
                    {
                        "uuid": "bex-1",
                        "status": "success",
                        "size": 42,
                        "scheduled_backup_uuid": "bkp-1",
                        "database_uuid": "db-1",
                    }
                ],
                id="backup_executions",
            ),
        ],
    )
    def test_binds_every_parent_id_and_projects_it_onto_the_rows(
        self,
        endpoint: str,
        responses: list[ScriptedResponse],
        expected_paths: list[str],
        expected_rows: list[dict],
    ) -> None:
        # A wrong resolve field leaves a `{placeholder}` in the child path or binds the wrong id,
        # and a wrong rename leaves the parent id under its framework-prefixed key, so the rows
        # can't be joined back. A parent deleted mid-sync must cost only its own rows.
        result = _driver().run(endpoint, responses)

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.rows == expected_rows


class TestCoolifyAuditEvents:
    def test_walks_to_the_last_page_and_drops_rows_shifted_by_new_events(self) -> None:
        # Coolify pages newest first, so an event recorded between page fetches pushes the last
        # row of page 1 onto page 2. The table replaces on every sync, so that row must not be
        # stored twice. Sensitive columns must never reach storage.
        result = _driver().run(
            "audit_events",
            [
                ScriptedResponse(
                    json={
                        "current_page": 1,
                        "last_page": 2,
                        "data": [
                            {"id": 3, "created_at": "2026-10-03T00:00:00.000000Z", "changes": {"password": "x"}},
                            {"id": 2, "created_at": "2026-10-02T00:00:00.000000Z", "actor_email": "a@example.com"},
                        ],
                    }
                ),
                ScriptedResponse(
                    json={
                        "current_page": 2,
                        "last_page": 2,
                        "data": [
                            {"id": 2, "created_at": "2026-10-02T00:00:00.000000Z", "actor_email": "a@example.com"},
                            {"id": 1, "created_at": "2026-10-01T00:00:00.000000Z", "ip_address": "192.0.2.1"},
                        ],
                    }
                ),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/audit-events", "/api/v1/audit-events"]
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page") == ["100", "100"]
        assert result.rows == [
            {"id": 3, "created_at": "2026-10-03T00:00:00.000000Z"},
            {"id": 2, "created_at": "2026-10-02T00:00:00.000000Z"},
            {"id": 1, "created_at": "2026-10-01T00:00:00.000000Z"},
        ]

    def test_a_page_count_past_the_safety_cap_fails_the_table_instead_of_truncating_it(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify.MAX_AUDIT_EVENTS_PAGES",
            2,
        ):
            result = _driver().run(
                "audit_events",
                [
                    ScriptedResponse(json={"last_page": 3, "data": [{"id": 2, "created_at": "2026-10-02T00:00:00Z"}]}),
                    ScriptedResponse(json={"last_page": 3, "data": [{"id": 1, "created_at": "2026-10-01T00:00:00Z"}]}),
                ],
            )

        # The first page already proves the walk can't complete, so no further page is fetched.
        assert isinstance(result.raised, AuditEventsPaginationTruncatedError)
        assert result.paths == ["/api/v1/audit-events"]

    @pytest.mark.parametrize(
        "status_code,expected",
        [
            pytest.param(200, None, id="admin_token"),
            pytest.param(403, AUDIT_EVENTS_FORBIDDEN_ERROR, id="member_token"),
            # Not a denial, so the table stays selectable and the sync reports the real error.
            pytest.param(500, None, id="server_error_is_not_a_denial"),
        ],
    )
    def test_reports_the_admin_only_audit_log_per_table(self, status_code: int, expected: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            permissions = CoolifySource().get_endpoint_permissions(
                CoolifySourceConfig(base_url=BASE_URL, api_token="coolify-token"),
                team_id=1,
                endpoints=["servers", "audit_events"],
            )

        assert permissions == {"servers": None, "audit_events": expected}
        assert {request.path for request in network.requests_log} == {"/api/v1/audit-events"}


class TestCoolifyValidateCredentials:
    def test_rejects_an_invalid_url_without_a_network_call(self) -> None:
        valid, error = validate_credentials("https://user@coolify.example.com", "coolify-token")
        assert not valid
        assert error is not None
        assert "instance URL" in error

    @pytest.mark.parametrize(
        "status_code,expected_valid,expected_fragment",
        [
            # Coolify answers an unrecognized token with 400 "Invalid token." rather than 401.
            pytest.param(400, False, "rejected the API token", id="invalid_token_400"),
        ],
    )
    def test_maps_status_to_a_message(
        self, status_code: int, expected_valid: bool, expected_fragment: str | None
    ) -> None:
        answer = ScriptedResponse(status=status_code, json={})
        with scripted_network(always(answer) if status_code == 500 else [answer]) as network:
            valid, error = validate_credentials(BASE_URL, "coolify-token", team_id=1)

        assert valid is expected_valid
        if expected_fragment is not None:
            assert error is not None and expected_fragment in error
        assert {request.path for request in network.requests_log} == {"/api/v1/teams"}
        assert all(request.headers["authorization"] == "Bearer coolify-token" for request in network.requests_log)

    def test_transport_error_does_not_blame_the_token(self) -> None:
        # An unreachable instance is not proof the token is bad; the message must point at the
        # URL, not tell the user to regenerate a good token.
        with scripted_network(always(ConnectionError("boom"))) as network:
            valid, error = validate_credentials(BASE_URL, "coolify-token", team_id=1)

        assert not valid
        assert error is not None and "reach" in error
        assert {request.path for request in network.requests_log} == {"/api/v1/teams"}
