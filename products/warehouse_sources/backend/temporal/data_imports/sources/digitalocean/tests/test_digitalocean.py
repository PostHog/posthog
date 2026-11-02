from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean import (
    digitalocean_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.settings import (
    DIGITALOCEAN_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source import DigitalOceanSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.digitalocean import (
    DigitalOceanSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(DigitalOceanSource(), DigitalOceanSourceConfig(api_key="dop_v1_token"))


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


class TestDigitalOceanGetResource:
    def test_images_limits_to_private(self) -> None:
        # Without private=true the images list also returns every public distribution/application
        # image — huge and identical for every account.
        resource = get_resource(DIGITALOCEAN_ENDPOINTS["images"])
        assert _endpoint(resource)["params"]["private"] == "true"


class TestDigitalOceanSensitiveFields:
    _DATABASE_RECORD = {
        "id": "db-1",
        "name": "prod-pg",
        "engine": "pg",
        "region": "nyc1",
        "connection": {"uri": "postgresql://doadmin:secret@host:25060/defaultdb", "password": "secret"},
        "private_connection": {"uri": "postgresql://doadmin:secret@priv-host:25060/defaultdb"},
        "standby_connection": {"password": "secret"},
        "standby_private_connection": {"password": "secret"},
        "users": [{"name": "doadmin", "password": "secret"}],
    }

    def test_apps_strips_nested_env_and_log_credentials(self) -> None:
        # App specs bury env-var values and log-destination credentials inside spec.services and
        # the deployment spec copy; the strip must recurse to reach them while keeping metadata.
        record = {
            "id": "app-1",
            "spec": {
                "name": "web",
                "services": [
                    {
                        "name": "api",
                        "envs": [{"key": "SECRET_KEY", "value": "leak-me"}],
                        "log_destinations": [{"name": "dd", "datadog": {"api_key": "leak-me"}}],
                    }
                ],
            },
            "active_deployment": {"spec": {"services": [{"name": "api", "envs": [{"value": "leak-me"}]}]}},
        }
        resource = digitalocean_source("dop_v1_token", "apps", team_id=1, job_id="job-1")
        [transformed] = resource._apply_transforms([record])

        assert transformed == {
            "id": "app-1",
            "spec": {"name": "web", "services": [{"name": "api"}]},
            "active_deployment": {"spec": {"services": [{"name": "api"}]}},
        }

    @pytest.mark.parametrize(
        "endpoint,capture_disabled",
        [
            pytest.param("databases", True, id="secrets_in_the_response"),
            pytest.param("invoice_summaries", True, id="billing_identity_in_the_response"),
            pytest.param("invoice_items", True, id="resource_level_spend_in_the_response"),
            pytest.param("database_backups", True, id="secrets_in_the_fanout_parent_response"),
            pytest.param("database_events", True, id="secrets_in_the_other_fanout_parent_response"),
            pytest.param("app_deployments", True, id="app_specs_in_the_parent_and_child_response"),
            pytest.param("app_events", True, id="app_specs_in_the_parent_and_embedded_deployments"),
            pytest.param("droplets", False, id="nothing_to_withhold"),
        ],
    )
    def test_capture_is_disabled_only_where_the_response_must_not_be_sampled(
        self, endpoint: str, capture_disabled: bool
    ) -> None:
        # Sample capture records the raw response before resource maps run, so stripping a field
        # from storage does not keep it out of a sample. An endpoint holding secrets or billing
        # identity must build its own capture-off session; every other endpoint uses the
        # tracked client's default (capture on).
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"apps": [], "databases": [], "droplets": [], "invoices": []})],
        )

        assert result.raised is None
        if capture_disabled:
            assert result.session_options == [{"redact_values": ("dop_v1_token",), "capture": False}]
        else:
            assert result.session_options == [{"redact_values": ("dop_v1_token",)}]


class TestDigitalOceanFanOut:
    @pytest.mark.parametrize(
        "endpoint,script,expected_paths,expected_rows",
        [
            pytest.param(
                "app_deployments",
                {
                    "/v2/apps": [ScriptedResponse(json={"apps": [{"id": "app-1"}]})],
                    "/v2/apps/app-1/deployments": [
                        ScriptedResponse(
                            json={
                                "deployments": [
                                    {
                                        "id": "dep-2",
                                        "phase": "ACTIVE",
                                        "spec": {
                                            "envs": [{"key": "TOKEN", "value": "leak-me"}],
                                            "services": [
                                                {
                                                    "name": "api",
                                                    "image": {"registry_credentials": "user:leak-me"},
                                                    "log_destinations": [{"logtail": {"token": "leak-me"}}],
                                                }
                                            ],
                                        },
                                    }
                                ],
                                "links": {
                                    "pages": {
                                        "next": "https://api.digitalocean.com/v2/apps/app-1/deployments?page=2&per_page=200"
                                    }
                                },
                            }
                        ),
                        ScriptedResponse(json={"deployments": [{"id": "dep-1", "phase": "SUPERSEDED"}], "links": {}}),
                    ],
                },
                ["/v2/apps", "/v2/apps/app-1/deployments", "/v2/apps/app-1/deployments"],
                [
                    {
                        "id": "dep-2",
                        "phase": "ACTIVE",
                        "spec": {"services": [{"name": "api", "image": {}}]},
                        "app_id": "app-1",
                    },
                    {"id": "dep-1", "phase": "SUPERSEDED", "app_id": "app-1"},
                ],
                id="child_pages_walked_and_nested_app_secrets_stripped",
            ),
            pytest.param(
                "uptime_check_states",
                {
                    "/v2/uptime/checks": [ScriptedResponse(json={"checks": [{"id": "chk-1"}, {"id": "chk-2"}]})],
                    "/v2/uptime/checks/chk-1/state": [
                        ScriptedResponse(json={"state": {"regions": {"us_east": {"status": "UP"}}}})
                    ],
                    "/v2/uptime/checks/chk-2/state": [
                        ScriptedResponse(
                            json={"state": {"regions": {"eu_west": {"status": "DOWN"}}, "previous_outage": None}}
                        )
                    ],
                },
                ["/v2/uptime/checks", "/v2/uptime/checks/chk-1/state", "/v2/uptime/checks/chk-2/state"],
                [
                    {"regions": {"us_east": {"status": "UP"}}, "check_id": "chk-1"},
                    {"regions": {"eu_west": {"status": "DOWN"}}, "previous_outage": None, "check_id": "chk-2"},
                ],
                id="single_state_object_becomes_one_row_per_check",
            ),
            pytest.param(
                "registry_repositories",
                {
                    "/v2/registries": [ScriptedResponse(json={"registries": [{"name": "reg-a"}]})],
                    "/v2/registries/reg-a/repositoriesV2": [
                        ScriptedResponse(
                            json={"repositories": [{"registry_name": "reg-a", "name": "web", "tag_count": 3}]}
                        )
                    ],
                },
                ["/v2/registries", "/v2/registries/reg-a/repositoriesV2"],
                [{"registry_name": "reg-a", "name": "web", "tag_count": 3}],
                id="parent_registry_name_does_not_replace_repository_name",
            ),
        ],
    )
    def test_child_rows_carry_their_parent_id(
        self,
        endpoint: str,
        script: dict[str, list[ScriptedResponse]],
        expected_paths: list[str],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(endpoint, route(script))

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.rows == expected_rows


class TestDigitalOceanValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            pytest.param(200, True, id="ok"),
            pytest.param(401, False, id="unauthorized"),
            pytest.param(403, False, id="forbidden"),
            pytest.param(500, False, id="server_error"),
        ],
    )
    def test_maps_status_to_validity(self, status_code: int, expected: bool) -> None:
        # The status code is returned alongside validity so the caller can tell an auth rejection
        # (401/403) apart from a transient failure (429/5xx) it must not report as an invalid token.
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("dop_v1_token") == (expected, status_code)

        assert {request.path for request in network.requests_log} == {"/v2/account"}
        assert network.requests_log[0].headers["authorization"] == "Bearer dop_v1_token"
        assert network.session_options == [{"redact_values": ("dop_v1_token",)}]

    def test_transport_error_reports_no_status(self) -> None:
        # A network failure must not surface as "token invalid"; it yields (False, None) so the
        # caller can distinguish it from a real auth rejection.
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("dop_v1_token") == (False, None)

        assert {request.path for request in network.requests_log} == {"/v2/account"}
