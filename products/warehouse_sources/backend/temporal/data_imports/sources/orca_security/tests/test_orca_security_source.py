from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OrcaSecuritySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.orca_security import (
    OrcaResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.source import OrcaSecuritySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOrcaSecuritySource:
    def setup_method(self):
        self.source = OrcaSecuritySource()
        self.team_id = 42

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ORCASECURITY

    def test_source_is_released(self):
        # A finished source must be visible: no unreleasedSource flag, soft ALPHA label.
        config = self.source.get_source_config
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_basics(self):
        config = self.source.get_source_config
        assert config.label == "Orca Security"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/orca-security"

    def test_source_config_fields(self):
        fields = {f.name: f for f in self.source.get_source_config.fields}
        assert set(fields) == {"api_token", "region"}

        token = fields["api_token"]
        assert isinstance(token, SourceFieldInputConfig)
        assert token.type == SourceFieldInputConfigType.PASSWORD
        assert token.required is True
        assert token.secret is True

        region = fields["region"]
        assert isinstance(region, SourceFieldSelectConfig)
        assert region.defaultValue == "global"
        assert {o.value for o in region.options} == {"global", "us", "eu"}

    def test_region_change_requires_credential_reentry(self):
        # `region` retargets where the stored token is sent, so editing it must force re-entering
        # the token — dropping this would let an editor redirect the preserved credential.
        assert self.source.connection_host_fields == ["region"]

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so public docs may render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_alerts_is_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(mock.MagicMock(), self.team_id)}
        assert schemas["alerts"].supports_incremental is True
        assert [f["field"] for f in schemas["alerts"].incremental_fields] == ["CreatedAt"]
        for name in ("assets", "cloud_accounts", "vulnerabilities"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filters_by_name(self):
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id, names=["alerts"])
        assert [s.name for s in schemas] == ["alerts"]

    def test_validate_credentials_delegates(self):
        config = OrcaSecuritySourceConfig(api_token="tok", region="us")
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.source.validate_orca_credentials",
            return_value=(True, None),
        ) as mock_validate:
            assert self.source.validate_credentials(config, self.team_id) == (True, None)
            mock_validate.assert_called_once_with("tok", "us")

    def test_non_retryable_errors_cover_auth(self):
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error: Unauthorized" in errors
        assert "403 Client Error: Forbidden" in errors

    def test_canonical_descriptions_present(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(ENDPOINTS).issubset(set(canonical))
        assert "id" in canonical["alerts"]["columns"]

    def test_resumable_manager_bound_to_data_class(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OrcaResumeConfig

    def test_source_for_pipeline_plumbs_config(self):
        config = OrcaSecuritySourceConfig(api_token="tok", region="eu")
        inputs = mock.MagicMock()
        inputs.schema_name = "alerts"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "CreatedAt"
        manager = mock.MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.source.orca_source"
        ) as mock_orca_source:
            self.source.source_for_pipeline(config, manager, inputs)

        mock_orca_source.assert_called_once_with(
            api_token="tok",
            region="eu",
            endpoint="alerts",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="CreatedAt",
        )

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self):
        config = OrcaSecuritySourceConfig(api_token="tok", region="global")
        inputs = mock.MagicMock()
        inputs.schema_name = "assets"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"
        inputs.incremental_field = None
        manager = mock.MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.source.orca_source"
        ) as mock_orca_source:
            self.source.source_for_pipeline(config, manager, inputs)

        assert mock_orca_source.call_args.kwargs["db_incremental_field_last_value"] is None
