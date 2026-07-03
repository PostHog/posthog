import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PersonioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio import PersonioResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.source import PersonioSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPersonioSource:
    def setup_method(self):
        self.source = PersonioSource()
        self.team_id = 123
        self.config = PersonioSourceConfig(client_id="client-id", client_secret="client-secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PERSONIO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Personio"
        assert config.label == "Personio"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/personio.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["client_id", "client_secret"]

    def test_client_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.personio.de/v2/auth/token",
            "400 Client Error: Bad Request for url: https://api.personio.de/v2/auth/token",
            "403 Client Error: Forbidden for url: https://api.personio.de/v2/persons?limit=50",
            "Personio rejected a freshly minted access token (401). The API credential may have been revoked or had its scope removed.",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.personio.de/v2/persons",
            # A mid-sync 401 on a data endpoint is handled by token re-mint, not disable.
            "401 Client Error: Unauthorized for url: https://api.personio.de/v2/persons",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # All shipped endpoints expose a server-side updated_at filter.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    def test_schemas_advertise_updated_at_cursor(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["persons"].incremental_fields == INCREMENTAL_FIELDS["persons"]
        assert [f["field"] for f in schemas["persons"].incremental_fields] == ["updated_at"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["persons"])
        assert len(schemas) == 1
        assert schemas[0].name == "persons"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Personio API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.source.validate_personio_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.client_id, self.config.client_secret)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PersonioResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.personio.source.personio_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_personio_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "persons"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_personio_source.assert_called_once()
        kwargs = mock_personio_source.call_args.kwargs
        assert kwargs["client_id"] == "client-id"
        assert kwargs["client_secret"] == "client-secret"
        assert kwargs["endpoint"] == "persons"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.personio.source.personio_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_personio_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "persons"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_personio_source.call_args.kwargs["db_incremental_field_last_value"] is None
