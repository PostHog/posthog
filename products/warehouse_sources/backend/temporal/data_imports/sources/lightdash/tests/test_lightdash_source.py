import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightdash import (
    LightdashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.source import LightdashSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestLightdashSource:
    def setup_method(self) -> None:
        self.source = LightdashSource()
        self.team_id = 123
        self.config = LightdashSourceConfig(instance_url="https://app.lightdash.cloud", api_token="tok")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.LIGHTDASH

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Lightdash"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/lightdash"
        assert config.iconPath == "/static/services/lightdash.png"

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        assert not self.source.get_source_config.unreleasedSource

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        input_fields = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert input_fields == ["instance_url", "api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_instance_url_field_is_not_secret(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "instance_url")
        assert field.secret is False
        assert field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # Lightdash exposes no server-side updated-since filter, so no stream is incremental.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["projects"])
        assert [s.name for s in schemas] == ["projects"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_cover_token_destination(self) -> None:
        # Dropping this would let an editor retarget the stored token at a host they control
        # without re-entering it (the update serializer keys off this list).
        assert self.source.connection_host_fields == ["instance_url"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://x.lightdash.cloud/api/v1/user",
            "403 Client Error: Forbidden for url: https://x.lightdash.cloud/api/v1/user",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "503 Server Error for url: https://x.lightdash.cloud/api/v1/user" for key in non_retryable
        )

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.source.validate_lightdash_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="projects")

        assert result == (True, None)
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["instance_url"] == "https://app.lightdash.cloud"
        assert kwargs["api_token"] == "tok"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["schema_name"] == "projects"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.source.lightdash_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_lightdash_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "spaces"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_lightdash_source.call_args.kwargs
        assert kwargs["instance_url"] == "https://app.lightdash.cloud"
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "spaces"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
