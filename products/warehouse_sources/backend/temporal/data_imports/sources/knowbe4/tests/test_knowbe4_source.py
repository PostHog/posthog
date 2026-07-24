import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.knowbe4 import (
    Knowbe4SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.source import Knowbe4Source
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestKnowBe4Source:
    def setup_method(self) -> None:
        self.source = Knowbe4Source()
        self.team_id = 123
        self.config = Knowbe4SourceConfig(api_key="tok", region="us")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.KNOWBE4

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Knowbe4"
        assert config.category == DataWarehouseSourceCategory.HR___RECRUITING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/knowbe4"

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        assert not self.source.get_source_config.unreleasedSource

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        input_fields = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        select_fields = [f.name for f in config.fields if isinstance(f, SourceFieldSelectConfig)]
        assert input_fields == ["api_key"]
        assert select_fields == ["region"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_region_options(self) -> None:
        config = self.source.get_source_config
        region = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert {o.value for o in region.options} == {"us", "eu", "ca", "uk", "de"}
        assert region.defaultValue == "us"

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # KnowBe4 exposes no server-side updated-since cursor on any list endpoint, so no
        # stream is incremental.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert [s.name for s in schemas] == ["users"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_cover_token_destination(self) -> None:
        # Dropping `region` would let an editor retarget the stored API key at a different
        # regional host without re-entering it (the update serializer keys off this list).
        assert self.source.connection_host_fields == ["region"]

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://us.api.knowbe4.com/v1/users",
            "Invalid KnowBe4 API key. Please check your key and try again.",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in "503 Server Error for url: https://us.api.knowbe4.com/v1/users" for key in non_retryable)

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.source.validate_knowbe4_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="users")

        assert result == (True, None)
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["api_key"] == "tok"
        assert kwargs["region"] == "us"
        assert kwargs["schema_name"] == "users"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.source.knowbe4_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_knowbe4_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "group_members"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_knowbe4_source.call_args.kwargs
        assert kwargs["api_key"] == "tok"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"] == "group_members"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
