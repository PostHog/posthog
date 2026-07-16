from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack import (
    source as better_stack_source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.better_stack import (
    BetterStackResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.source import BetterStackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBetterStackSourceConfig:
    def test_source_type(self) -> None:
        assert BetterStackSource().source_type == ExternalDataSourceType.BETTERSTACK

    def test_config_basics(self) -> None:
        config = BetterStackSource().get_source_config
        assert config.label == "Better Stack"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible — the scaffold's unreleasedSource flag must stay gone.
        assert not config.unreleasedSource

    def test_single_password_api_token_field(self) -> None:
        fields = BetterStackSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_token"
        assert field.required is True
        assert field.type == SourceFieldInputConfigType.PASSWORD


class TestBetterStackGetSchemas:
    def test_returns_every_endpoint(self) -> None:
        schemas = BetterStackSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            # Only incidents has a server-side date filter; everything else is full refresh.
            ("incidents", True),
            ("monitors", False),
            ("monitor_groups", False),
            ("heartbeats", False),
            ("heartbeat_groups", False),
            ("status_pages", False),
            ("on_calls", False),
            ("escalation_policies", False),
        ]
    )
    def test_incremental_support_matches_settings(self, endpoint: str, expected_incremental: bool) -> None:
        schemas = {s.name: s for s in BetterStackSource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        assert bool(schema.incremental_fields) is expected_incremental

    def test_names_filter(self) -> None:
        schemas = BetterStackSource().get_schemas(MagicMock(), team_id=1, names=["incidents", "monitors"])
        assert {s.name for s in schemas} == {"incidents", "monitors"}


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
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = BetterStackSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BetterStackResumeConfig

    @parameterized.expand(
        [
            # Incidents partition on the stable started_at; ordering is unverified so the watermark
            # commits at end of sync (sort_mode="desc").
            ("incidents", ["started_at"], "datetime", "desc"),
            ("monitors", ["created_at"], "datetime", "asc"),
            ("heartbeats", ["created_at"], "datetime", "asc"),
            # Small collections whose timestamp columns aren't confirmed don't partition.
            ("monitor_groups", None, None, "asc"),
            ("status_pages", None, None, "asc"),
            ("on_calls", None, None, "asc"),
            ("escalation_policies", None, None, "asc"),
        ]
    )
    def test_source_for_pipeline_per_endpoint(
        self, endpoint: str, expected_keys: list[str] | None, expected_mode: str | None, expected_sort: str
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.should_use_incremental_field = False
        response = BetterStackSource().source_for_pipeline(
            MagicMock(api_token="bs_test"), resumable_source_manager=MagicMock(), inputs=inputs
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
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
