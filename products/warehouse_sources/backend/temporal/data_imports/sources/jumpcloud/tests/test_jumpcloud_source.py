from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.jumpcloud import JumpcloudResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source import JumpcloudSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "key", org_id: str | None = None, region: str = "us") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.org_id = org_id
    config.region = region
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert JumpcloudSource().source_type == ExternalDataSourceType.JUMPCLOUD

    def test_config_is_visible_and_alpha(self) -> None:
        config = JumpcloudSource().get_source_config
        # A finished source must not be hidden from users.
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/jumpcloud"

    def test_fields(self) -> None:
        fields = {f.name: f for f in JumpcloudSource().get_source_config.fields}
        assert set(fields) == {"api_key", "region", "org_id"}

        api_key = fields["api_key"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True

        region = fields["region"]
        assert isinstance(region, SourceFieldSelectConfig)
        assert region.defaultValue == "us"
        assert {option.value for option in region.options} == {"us", "eu"}

        org_id = fields["org_id"]
        assert isinstance(org_id, SourceFieldInputConfig)
        assert org_id.required is False
        assert org_id.secret is False

    def test_connection_host_fields_force_secret_reentry_on_retarget(self) -> None:
        # Changing org_id or region retargets the stored API key (different organization's
        # data, or a different regional host), so both must force re-entering the key.
        assert JumpcloudSource().connection_host_fields == ["org_id", "region"]


class TestGetSchemas:
    def test_only_events_is_incremental(self) -> None:
        schemas = {s.name: s for s in JumpcloudSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        assert schemas["events"].supports_incremental is True
        assert [f["field"] for f in schemas["events"].incremental_fields] == ["timestamp"]
        # The start_time boundary can re-return the watermark row, so append would duplicate it.
        assert all(not s.supports_append for s in schemas.values())
        # The REST entity endpoints have no server-side "updated since" filter.
        assert all(not schema.supports_incremental for name, schema in schemas.items() if name != "events")

    def test_primary_keys_follow_api_family(self) -> None:
        schemas = {s.name: s for s in JumpcloudSource().get_schemas(_config(), team_id=1)}
        # v1 resources use Mongo-style `_id`; v2 groups and Insights events use `id`.
        assert schemas["users"].detected_primary_keys == ["_id"]
        assert schemas["user_groups"].detected_primary_keys == ["id"]
        assert schemas["events"].detected_primary_keys == ["id"]

    def test_names_filter(self) -> None:
        schemas = JumpcloudSource().get_schemas(_config(), team_id=1, names=["users", "events"])
        assert {s.name for s in schemas} == {"users", "events"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert JumpcloudSource.lists_tables_without_credentials is True
        tables = JumpcloudSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        events = next(t for t in tables if t["name"] == "events")
        assert "Incremental" in events["sync_methods"]


class TestValidateCredentials:
    def test_plumbs_config_and_schema_name(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source.validate_jumpcloud_credentials",
            return_value=(True, None),
        ) as mocked:
            ok, error = JumpcloudSource().validate_credentials(
                _config(org_id="org1", region="eu"), team_id=1, schema_name="systems"
            )
        assert ok is True
        assert error is None
        mocked.assert_called_once_with("key", "org1", "eu", "systems")

    def test_failure_is_propagated(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source.validate_jumpcloud_credentials",
            return_value=(False, "Invalid JumpCloud API key"),
        ):
            ok, error = JumpcloudSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error == "Invalid JumpCloud API key"


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = JumpcloudSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is JumpcloudResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "events"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-07-01T00:00:00Z"
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source.jumpcloud_source"
        ) as mocked:
            JumpcloudSource().source_for_pipeline(_config(org_id="org1", region="eu"), manager, inputs)
        mocked.assert_called_once_with(
            api_key="key",
            endpoint="events",
            logger=inputs.logger,
            resumable_source_manager=manager,
            org_id="org1",
            region="eu",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01T00:00:00Z",
        )

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "users"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-07-01T00:00:00Z"
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source.jumpcloud_source"
        ) as mocked:
            JumpcloudSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized_console",
                "401 Client Error: Unauthorized for url: https://console.jumpcloud.com/api/systemusers?limit=100",
            ),
            (
                "forbidden_insights",
                "403 Client Error: Forbidden for url: https://api.jumpcloud.com/insights/directory/v1/events",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = JumpcloudSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='console.jumpcloud.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://console.jumpcloud.com/api/systems",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://console.jumpcloud.com/api/systemusers",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = JumpcloudSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))

    def test_source_exposes_canonical_descriptions(self) -> None:
        assert JumpcloudSource().get_canonical_descriptions() is CANONICAL_DESCRIPTIONS
