import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    SolarwindsServiceDeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.solarwinds_service_desk import (
    SolarwindsServiceDeskResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.source import (
    SolarwindsServiceDeskSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.source"


class TestSolarwindsServiceDeskSource:
    def setup_method(self) -> None:
        self.source = SolarwindsServiceDeskSource()
        self.team_id = 123
        self.config = SolarwindsServiceDeskSourceConfig(api_token="swsd-token", region="eu")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SOLARWINDSSERVICEDESK

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "SolarwindsServiceDesk"
        assert config.label == "SolarWinds Service Desk"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Deliberately hidden until the sync has been exercised against a live account.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/solarwinds-service-desk"

        field_names = [f.name for f in config.fields]
        assert field_names == ["region", "api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_region_field_covers_documented_hosts(self) -> None:
        config = self.source.get_source_config
        region = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert [option.value for option in region.options] == ["us", "eu", "au"]
        assert region.defaultValue == "us"

    def test_region_is_a_connection_host_field(self) -> None:
        # The token is sent to the host derived from `region`; retargeting the region must force
        # re-entering the token, or an editor could exfiltrate it to another regional stack.
        assert self.source.connection_host_fields == ["region"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        # Only /incidents documents a server-side updated_from filter.
        assert schemas["incidents"].supports_incremental is True
        assert [f["field"] for f in schemas["incidents"].incremental_fields] == ["updated_at"]
        for name, schema in schemas.items():
            if name not in INCREMENTAL_FIELDS:
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["incidents"])
        assert len(schemas) == 1
        assert schemas[0].name == "incidents"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("unauthorized_us", "401 Client Error: Unauthorized for url: https://api.samanage.com/incidents.json"),
            ("forbidden_eu", "403 Client Error: Forbidden for url: https://apieu.samanage.com/users.json"),
            ("unauthorized_au", "401 Client Error: Unauthorized for url: https://apiau.samanage.com/problems.json"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.samanage.com"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://apieu.samanage.com"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            # At create only the token is probed; per-schema validation probes that endpoint's path.
            ("at_create", None, None),
            ("for_schema", "incidents", "/incidents.json"),
            ("unknown_schema", "not_a_table", None),
        ]
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_credentials")
    def test_validate_credentials_probes_the_right_path(
        self, _name: str, schema_name: str | None, expected_path: str | None, mock_validate: mock.MagicMock
    ) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name)
        mock_validate.assert_called_once_with("eu", "swsd-token", expected_path)
        assert result == (True, None)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SolarwindsServiceDeskResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.solarwinds_service_desk_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "incidents"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-05T08:30:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["api_token"] == "swsd-token"
        assert kwargs["endpoint"] == "incidents"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-05T08:30:00Z"

    @mock.patch(f"{_SOURCE_MODULE}.solarwinds_service_desk_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "incidents"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-05T08:30:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown SolarWinds Service Desk schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
