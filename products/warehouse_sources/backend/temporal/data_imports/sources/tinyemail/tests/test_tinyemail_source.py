import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tinyemail import (
    TinyemailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.source import TinyemailSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTinyemailSource:
    def setup_method(self) -> None:
        self.source = TinyemailSource()
        self.team_id = 123
        self.config = TinyemailSourceConfig(api_key="tinyemail-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TINYEMAIL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Tinyemail"
        assert config.label == "tinyEmail"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/tinyemail"
        assert config.iconPath == "/static/services/tinyemail.png"
        assert self.source.lists_tables_without_credentials is True

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["api_key"]
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # tinyEmail has no server-side timestamp filter on any endpoint, so nothing
        # may advertise incremental or append sync.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns"])
        assert [s.name for s in schemas] == ["campaigns"]

    @pytest.mark.parametrize(
        "observed_error,expected_non_retryable",
        [
            ("401 Client Error: Unauthorized for url: https://api.tinyemail.com/v1/campaign", True),
            ("403 Client Error: Forbidden for url: https://api.tinyemail.com/v1/contacts", True),
            ("429 Client Error: Too Many Requests for url: https://api.tinyemail.com/v1/campaign", False),
            ("500 Server Error: Internal Server Error for url: https://api.tinyemail.com/v1/campaign", False),
        ],
    )
    def test_non_retryable_errors(self, observed_error: str, expected_non_retryable: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expected_non_retryable

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.source.validate_tinyemail_credentials"
    )
    def test_validate_credentials_plumbs_api_key(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.kwargs["api_key"] == "tinyemail-key"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.source.tinyemail_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_tinyemail_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contact_members"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_tinyemail_source.call_args.kwargs
        assert kwargs["api_key"] == "tinyemail-key"
        assert kwargs["endpoint"] == "contact_members"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
