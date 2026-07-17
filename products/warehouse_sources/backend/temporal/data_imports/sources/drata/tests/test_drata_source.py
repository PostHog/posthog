import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.drata import DrataResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.source import DrataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DrataSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDrataSource:
    def setup_method(self) -> None:
        self.source = DrataSource()
        self.team_id = 123
        self.config = DrataSourceConfig(api_key="drata_key", region="EU")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DRATA

    def test_source_is_visible_with_alpha_release_status(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Drata"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/drata"

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_region_field_offers_every_drata_region(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert field.defaultValue == "US"
        assert [o.value for o in field.options] == ["US", "EU", "APAC"]

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_events_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["events"].supports_incremental is True
        assert [f["field"] for f in schemas["events"].incremental_fields] == ["createdAt"]
        for name, schema in schemas.items():
            if name == "events":
                continue
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_feature_gated_risk_tables_are_deselected_by_default(self) -> None:
        # Risk endpoints 403 on accounts without Drata's Risk Management Pro feature; enabling them
        # by default would fail the first sync for most accounts.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["risk_registers"].should_sync_default is False
        assert schemas["risks"].should_sync_default is False
        assert schemas["controls"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["events", "nope"])
        assert [s.name for s in schemas] == ["events"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # Exercises the placeholder-config path the public docs endpoint uses (no credentials).
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["controls"]["primary_keys"] == ["workspaceId", "id"]

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://public-api.drata.com/public/v2/users",),
            ("403 Client Error: Forbidden for url: https://public-api.eu.drata.com/public/v2/risk-registers",),
            ("412 Client Error: Precondition Failed for url: https://public-api.apac.drata.com/public/v2/events",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures_in_every_region(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://public-api.drata.com/public/v2/users",),
            ("429 Client Error: Too Many Requests for url: https://public-api.drata.com/public/v2/events",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drata.source.validate_credentials")
    def test_validate_credentials_passes_key_and_region(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Drata API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid Drata API key")
        mock_validate.assert_called_once_with("drata_key", "EU")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DrataResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drata.source.drata_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "createdAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "drata_key"
        assert kwargs["region"] == "EU"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "createdAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drata.source.drata_source")
    def test_source_for_pipeline_drops_incremental_value_when_disabled(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Drata schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
