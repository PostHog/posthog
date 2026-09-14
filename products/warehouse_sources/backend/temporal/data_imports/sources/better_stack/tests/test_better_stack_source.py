from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack import (
    source as better_stack_source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.source import BetterStackSource


class TestBetterStackSourceConfig:
    def test_config_basics(self) -> None:
        config = BetterStackSource().get_source_config
        assert config.label == "Better Stack"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible — the scaffold's unreleasedSource flag must stay gone.
        assert not config.unreleasedSource


class TestBetterStackGetSchemas:
    @parameterized.expand(
        [
            # (endpoint, supports_incremental, supports_append)
            # Incidents has a server-side date filter, so appending only ever adds newer rows.
            ("incidents", True, True),
            # Fan-out children re-read each parent's whole child collection every sync, so they
            # merge on the primary key and must not offer append.
            ("incident_comments", True, False),
            ("monitor_response_times", True, False),
            # Everything else is full refresh.
            ("monitors", False, False),
            ("monitor_availability", False, False),
            ("monitor_groups", False, False),
            ("heartbeats", False, False),
            ("heartbeat_groups", False, False),
            ("status_pages", False, False),
            ("on_calls", False, False),
            ("escalation_policies", False, False),
            ("team_members", False, False),
            ("roles", False, False),
        ]
    )
    def test_sync_modes_match_settings(self, endpoint: str, expected_incremental: bool, expected_append: bool) -> None:
        schemas = {s.name: s for s in BetterStackSource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_append
        assert bool(schema.incremental_fields) is expected_incremental


class TestBetterStackValidateCredentials:
    @parameterized.expand(
        [
            # (probe status, schema_name, expected_ok)
            ("ok", 200, None, True),
            ("ok_for_schema", 200, "incidents", True),
            # A 403 at source-create is a genuine token scoped away from the probe resource — accept it.
            ("forbidden_at_create_accepted", 403, None, True),
            # A 403 while configuring a specific schema means no access to that resource — reject.
            ("forbidden_for_schema_rejected", 403, "incidents", False),
            ("unauthorized_rejected", 401, None, False),
            ("connection_failure_rejected", None, None, False),
            ("unexpected_status_rejected", 500, None, False),
        ]
    )
    def test_status_mapping(
        self, _name: str, probe_status: int | None, schema_name: str | None, expected_ok: bool
    ) -> None:
        with mock.patch.object(better_stack_source_module, "probe_credentials", return_value=probe_status):
            ok, error = BetterStackSource().validate_credentials(
                MagicMock(api_token="bs_test"), team_id=1, schema_name=schema_name
            )
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestBetterStackNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://uptime.betterstack.com/api/v2/monitors?per_page=250",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://uptime.betterstack.com/api/v3/incidents"),
            # Team members and roles are served from the account-level host, which needs its own
            # entries — the Uptime-host patterns don't match a URL on it.
            ("org_host_unauthorized", "401 Client Error: Unauthorized for url: https://betterstack.com/api/v2/roles"),
            (
                "org_host_forbidden",
                "403 Client Error: Forbidden for url: https://betterstack.com/api/v2/team-members?per_page=50",
            ),
            # A multi-team token can't resolve which team's members to list.
            (
                "team_members_needs_a_team_scoped_token",
                "422 Client Error: Unprocessable Entity for url: https://betterstack.com/api/v2/team-members?per_page=50",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = BetterStackSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://uptime.betterstack.com/api/v3/incidents",
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://uptime.betterstack.com/api/v2/monitors",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='uptime.betterstack.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = BetterStackSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestBetterStackResumableAndPipeline:
    @parameterized.expand(
        [
            # (endpoint, primary keys, partition keys, partition mode, sort mode)
            # Incidents partition on the stable started_at; ordering is unverified so the watermark
            # commits at end of sync (sort_mode="desc").
            ("incidents", ["id"], ["started_at"], "datetime", "desc"),
            ("monitors", ["id"], ["created_at"], "datetime", "asc"),
            ("heartbeats", ["id"], ["created_at"], "datetime", "asc"),
            # Fan-out rows arrive parent by parent, so their watermark commits at end of sync too.
            # Their keys carry the parent id, without which every parent's rows collide.
            ("incident_comments", ["incident_id", "id"], ["created_at"], "datetime", "desc"),
            ("monitor_response_times", ["monitor_id", "region", "at"], ["at"], "datetime", "desc"),
            ("monitor_availability", ["monitor_id"], None, None, "asc"),
            # Members and pending invitations draw ids from separate spaces.
            ("team_members", ["id", "type"], None, None, "asc"),
            ("roles", ["id"], None, None, "asc"),
            # Small collections whose timestamp columns aren't confirmed don't partition.
            ("monitor_groups", ["id"], None, None, "asc"),
            ("status_pages", ["id"], None, None, "asc"),
            ("on_calls", ["id"], None, None, "asc"),
            ("escalation_policies", ["id"], None, None, "asc"),
        ]
    )
    def test_source_for_pipeline_per_endpoint(
        self,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_keys: list[str] | None,
        expected_mode: str | None,
        expected_sort: str,
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.should_use_incremental_field = False
        manager = MagicMock()
        manager.can_resume.return_value = False
        response = BetterStackSource().source_for_pipeline(
            MagicMock(api_token="bs_test"), resumable_source_manager=manager, inputs=inputs
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_keys == expected_keys
        assert response.partition_mode == expected_mode
        assert response.sort_mode == expected_sort


class TestBetterStackCanonicalDescriptions:
    def test_descriptions_keyed_by_endpoint_name(self) -> None:
        descriptions = BetterStackSource().get_canonical_descriptions()
        # Every documented key must be a real endpoint so enrichment binds to the right table.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "incidents" in descriptions
        assert descriptions["incidents"]["columns"]["id"]
