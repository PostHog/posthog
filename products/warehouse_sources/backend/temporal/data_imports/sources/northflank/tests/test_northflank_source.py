from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NorthflankSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.source import NorthflankSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestNorthflankSource:
    def setup_method(self):
        self.source = NorthflankSource()
        self.team_id = 123
        self.config = NorthflankSourceConfig(api_token="nf-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.NORTHFLANK

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Northflank"
        assert config.label == "Northflank"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible: it must not carry the scaffolding hide flag.
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/northflank.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/northflank"

        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig))
        assert token_field.name == "api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.northflank.com/v1/projects?per_page=1",),
            ("403 Client Error: Forbidden for url: https://api.northflank.com/v1/projects/abc/services",),
        ]
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://api.northflank.com/v1/projects",),
            ("500 Server Error for url: https://api.northflank.com/v1/projects",),
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",),
        ]
    )
    def test_non_retryable_errors_ignore_transient_and_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_no_endpoint_advertises_incremental(self, endpoint):
        # Northflank exposes no server-side timestamp filter, so every table is full refresh.
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["services"])
        assert [s.name for s in schemas] == ["services"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self):
        # The static endpoint catalog powers the public docs' Supported tables section.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        for table in tables:
            assert "Full refresh" in table["sync_methods"]

    @parameterized.expand(
        [
            ((True, None), True),
            ((False, "Invalid Northflank API token. Please check that your token is valid and not revoked."), False),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.northflank.source.validate_northflank_credentials"
    )
    def test_validate_credentials_plumbs_result(self, mock_return, expected_valid, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid
        mock_validate.assert_called_once_with("nf-token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.northflank.source.northflank_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_northflank_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "services"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_northflank_source.call_args.kwargs
        assert kwargs["api_token"] == "nf-token"
        assert kwargs["endpoint"] == "services"
        assert kwargs["logger"] is inputs.logger
