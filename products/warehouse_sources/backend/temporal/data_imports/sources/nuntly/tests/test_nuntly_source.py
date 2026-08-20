from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuntly import NuntlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.nuntly import NuntlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.source import NuntlySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestNuntlySource:
    def setup_method(self) -> None:
        self.source = NuntlySource()
        self.team_id = 123
        self.config = NuntlySourceConfig(api_key="apk_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.NUNTLY

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Nuntly"
        assert config.label == "Nuntly"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/nuntly.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/nuntly"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    @parameterized.expand(
        [
            (
                "401 Client Error: Unauthorized for url: https://api.nuntly.com/emails?limit=30",
                True,
            ),
            (
                "403 Client Error: Forbidden for url: https://api.nuntly.com/messages?limit=30",
                True,
            ),
            (
                "429 Client Error: Too Many Requests for url: https://api.nuntly.com/emails",
                False,
            ),
            (
                "500 Server Error: Internal Server Error for url: https://api.nuntly.com/emails",
                False,
            ),
        ]
    )
    def test_non_retryable_errors(self, observed_error: str, expected_match: bool) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors) is expected_match

    def test_get_schemas_match_endpoints_full_refresh_only(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            # Nuntly documents no server-side timestamp filter on any list endpoint.
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Emails"])
        assert len(schemas) == 1
        assert schemas[0].name == "Emails"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["Nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    @parameterized.expand(
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.source.validate_nuntly_credentials"
    )
    def test_validate_credentials(
        self, probe_valid: bool, expected_valid: bool, expected_message: str | None, mock_validate: mock.Mock
    ) -> None:
        mock_validate.return_value = (probe_valid, 200 if probe_valid else 401)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("apk_test")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is NuntlyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.source.nuntly_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_nuntly_source: mock.Mock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Emails"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_nuntly_source.assert_called_once_with(
            api_key="apk_test",
            endpoint="Emails",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
        )
