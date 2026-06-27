import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.source import AdRollSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AdRollSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAdRollSource:
    def setup_method(self):
        self.source = AdRollSource()
        self.team_id = 123
        self.config = AdRollSourceConfig(client_id="cid", personal_access_token="pat")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ADROLL

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "AdRoll"
        assert config.label == "AdRoll"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/adroll.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["client_id", "personal_access_token"]

    def test_pat_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "personal_access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://services.adroll.com/api/v1/organization/get_advertisables",
            "403 Client Error: Forbidden for url: https://services.adroll.com/api/v1/campaign/get_all",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://services.adroll.com/api/v1/ad/get_all",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns"])
        assert len(schemas) == 1
        assert schemas[0].name == "campaigns"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AdRoll credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.adroll.source.validate_adroll_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("cid", "pat")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.adroll.source.adroll_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_adroll_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "campaigns"

        self.source.source_for_pipeline(self.config, inputs)

        mock_adroll_source.assert_called_once()
        kwargs = mock_adroll_source.call_args.kwargs
        assert kwargs["client_id"] == "cid"
        assert kwargs["personal_access_token"] == "pat"
        assert kwargs["endpoint"] == "campaigns"
