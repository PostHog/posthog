import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HatchetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet import (
    HatchetConnection,
    HatchetResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.source import HatchetSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHatchetSource:
    def setup_method(self):
        self.source = HatchetSource()
        self.team_id = 123
        self.config = HatchetSourceConfig(api_token="tok", host=None, tenant_id=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HATCHET

    def test_config_fields(self):
        field_names = {f.name for f in self.source.get_source_config.fields}
        assert field_names == {"api_token", "host", "tenant_id"}

        api_token = next(f for f in self.source.get_source_config.fields if f.name == "api_token")
        # The token is a secret; the wizard must render it as a password input.
        assert isinstance(api_token, SourceFieldInputConfig)
        assert api_token.required is True
        assert api_token.type == SourceFieldInputConfigType.PASSWORD

    def test_host_is_a_connection_host_field(self):
        # The token is sent to `host`; retargeting it must force re-entry of the token secret.
        assert self.source.connection_host_fields == ["host"]

    @pytest.mark.parametrize(
        "endpoint,expected_incremental,expected_primary_keys",
        [
            ("workflow_runs", True, ["id"]),
            ("tasks", True, ["id"]),
            ("events", True, ["id"]),
            ("event_keys", False, ["key"]),
        ],
    )
    def test_get_schemas(self, endpoint, expected_incremental, expected_primary_keys):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        assert schema.detected_primary_keys == expected_primary_keys

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_auth_errors_are_non_retryable(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is HatchetResumeConfig

    def test_validate_credentials_delegates_with_resolved_overrides(self):
        config = HatchetSourceConfig(api_token="tok", host="", tenant_id="")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.source.validate_hatchet_credentials",
            return_value=(True, None),
        ) as validate:
            result = self.source.validate_credentials(config, self.team_id)

        assert result == (True, None)
        # Empty override strings collapse to None so the token-derived values are used; team_id is
        # forwarded so the credential probe can SSRF-check the resolved host.
        validate.assert_called_once_with("tok", None, None, self.team_id)

    def test_source_for_pipeline_plumbs_endpoint_and_connection(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "workflow_runs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"
        manager = mock.MagicMock()
        connection = HatchetConnection(base_url="https://cloud.example", tenant_id="tenant-1")

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.source.resolve_connection",
                return_value=connection,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.source.hatchet_source"
            ) as hatchet_source,
        ):
            self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = hatchet_source.call_args
        assert kwargs["endpoint"] == "workflow_runs"
        assert kwargs["connection"] is connection
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-06-01T00:00:00Z"

    def test_source_for_pipeline_drops_incremental_value_on_full_refresh(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.source.resolve_connection",
                return_value=HatchetConnection(base_url="https://cloud.example", tenant_id="t"),
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.source.hatchet_source"
            ) as hatchet_source,
        ):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        _, kwargs = hatchet_source.call_args
        # A stale watermark must not leak into a full-refresh run.
        assert kwargs["db_incremental_field_last_value"] is None

    def test_documented_tables_render_from_static_catalog(self):
        # lists_tables_without_credentials must expose the table catalog (+ canonical descriptions)
        # for the public docs <SourceTables /> component without needing credentials.
        assert self.source.lists_tables_without_credentials is True

        tables = {t["name"]: t for t in self.source.get_documented_tables()}

        assert set(tables) == {"workflow_runs", "tasks", "events", "event_keys"}
        assert tables["workflow_runs"]["description"]
        assert "Incremental" in tables["workflow_runs"]["sync_methods"]
        assert tables["event_keys"]["sync_methods"] == ["Full refresh"]
