import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KandjiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.source import KandjiSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestKandjiSource:
    def setup_method(self) -> None:
        self.source = KandjiSource()
        self.team_id = 123
        self.config = KandjiSourceConfig(api_token="tok", subdomain="accuhive", region="us")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.KANDJI

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Kandji"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/kandji"

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        assert not self.source.get_source_config.unreleasedSource

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        input_fields = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        select_fields = [f.name for f in config.fields if isinstance(f, SourceFieldSelectConfig)]
        assert input_fields == ["api_token", "subdomain"]
        assert select_fields == ["region"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_region_options(self) -> None:
        config = self.source.get_source_config
        region = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert {o.value for o in region.options} == {"us", "eu"}
        assert region.defaultValue == "us"

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # Kandji exposes no server-side updated-since cursor, so no stream is incremental.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["devices"])
        assert [s.name for s in schemas] == ["devices"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://accuhive.api.kandji.io/api/v1/devices",
            "403 Client Error: Forbidden for url: https://accuhive.api.kandji.io/api/v1/devices",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "503 Server Error for url: https://accuhive.api.kandji.io/api/v1/devices" for key in non_retryable
        )

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kandji.source.validate_kandji_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="devices")

        assert result == (True, None)
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["api_token"] == "tok"
        assert kwargs["subdomain"] == "accuhive"
        assert kwargs["region"] == "us"
        assert kwargs["schema_name"] == "devices"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.kandji.source.kandji_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_kandji_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "device_apps"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_kandji_source.call_args.kwargs
        assert kwargs["api_token"] == "tok"
        assert kwargs["subdomain"] == "accuhive"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"] == "device_apps"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
