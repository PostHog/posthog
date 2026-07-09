from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.alguna import AlgunaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.source import AlgunaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AlgunaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAlgunaSource:
    def setup_method(self):
        self.source = AlgunaSource()
        self.team_id = 123
        self.config = AlgunaSourceConfig(api_key="alg-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ALGUNA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Alguna"
        assert config.label == "Alguna"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Deliberately gated while the endpoint behavior is unverified against a live account.
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/alguna.svg"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.alguna.io/customers?limit=100&offset=0",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.alguna.io/invoices?limit=100&offset=0"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("other_vendor", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("server_error", "500 Server Error for url: https://api.alguna.io/customers"),
        ]
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, _name, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No list payload carries the API's filterable date fields, so no stream can track an
        # incremental watermark — advertising incremental here would corrupt syncs.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["invoices"])
        assert len(schemas) == 1
        assert schemas[0].name == "invoices"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Alguna API key"),
        ]
    )
    def test_validate_credentials(self, _name, mock_return, expected_valid, expected_message):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.alguna.source.validate_alguna_credentials"
        ) as mock_validate:
            mock_validate.return_value = mock_return

            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

            assert is_valid is expected_valid
            assert error_message == expected_message
            mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AlgunaResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.alguna.source.alguna_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_alguna_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_alguna_source.assert_called_once()
        kwargs = mock_alguna_source.call_args.kwargs
        assert kwargs["api_key"] == "alg-key"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_declared_endpoints(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
