import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source import AirtableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AirtableSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAirtableSource:
    def setup_method(self):
        self.source = AirtableSource()
        self.team_id = 123
        self.config = AirtableSourceConfig(personal_access_token="pat-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.AIRTABLE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Airtable"
        assert config.label == "Airtable"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/airtable.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["personal_access_token"]

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
            "401 Client Error: Unauthorized for url: https://api.airtable.com/v0/meta/bases",
            "403 Client Error: Forbidden for url: https://api.airtable.com/v0/app1/tbl1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.airtable.com/v0/meta/bases",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only records can be filtered server-side (CREATED_TIME() formula).
        assert incremental == {"records"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["records"].incremental_fields == INCREMENTAL_FIELDS["records"]
        assert [f["field"] for f in schemas["records"].incremental_fields] == ["createdTime"]
        assert schemas["bases"].incremental_fields == []
        assert schemas["bases"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["records"])
        assert len(schemas) == 1
        assert schemas[0].name == "records"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Airtable personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source.validate_airtable_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.personal_access_token)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source.airtable_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_airtable_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "records"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"

        self.source.source_for_pipeline(self.config, inputs)

        mock_airtable_source.assert_called_once()
        kwargs = mock_airtable_source.call_args.kwargs
        assert kwargs["personal_access_token"] == "pat-token"
        assert kwargs["endpoint"] == "records"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source.airtable_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_airtable_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "records"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"

        self.source.source_for_pipeline(self.config, inputs)

        assert mock_airtable_source.call_args.kwargs["db_incremental_field_last_value"] is None
