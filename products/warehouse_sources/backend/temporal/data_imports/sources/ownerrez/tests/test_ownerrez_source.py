import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ownerrez import (
    OwnerrezSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.ownerrez import OwnerRezResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source import OwnerrezSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = {"Bookings", "Quotes", "Reviews"}
_FULL_REFRESH_ENDPOINTS = {"Payments", "Guests", "Properties", "Deposits", "Fees", "Refunds"}


class TestOwnerrezSource:
    def setup_method(self):
        self.source = OwnerrezSource()
        self.team_id = 123
        self.config = OwnerrezSourceConfig(email="host@example.com", api_key="pt_key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OWNERREZ

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Ownerrez"
        assert config.label == "OwnerRez"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/ownerrez.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/ownerrez"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["email", "api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_email_field_is_not_secret(self):
        config = self.source.get_source_config
        email_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "email")
        assert email_field.type == SourceFieldInputConfigType.EMAIL
        assert email_field.secret is False
        assert email_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.ownerrez.com/v2/bookings?limit=100",
            "403 Client Error: Forbidden for url: https://api.ownerrez.com/v2/guests?limit=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.ownerrez.com/v2/bookings",
            "500 Server Error: Internal Server Error for url: https://api.ownerrez.com/v2/bookings",
            "HTTPSConnectionPool(host='api.ownerrez.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["updated_utc"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Bookings"])
        assert len(schemas) == 1
        assert schemas[0].name == "Bookings"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid OwnerRez account email or personal access token"),
            (
                (False, 403),
                False,
                "Could not connect to OwnerRez with the provided account email and personal access token",
            ),
            (
                (False, None),
                False,
                "Could not connect to OwnerRez with the provided account email and personal access token",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source.validate_ownerrez_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("host@example.com", "pt_key")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is OwnerRezResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source.ownerrez_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_ownerrez_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Bookings"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_ownerrez_source.assert_called_once()
        kwargs = mock_ownerrez_source.call_args.kwargs
        assert kwargs["email"] == "host@example.com"
        assert kwargs["api_key"] == "pt_key"
        assert kwargs["endpoint"] == "Bookings"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source.ownerrez_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_ownerrez_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Properties"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_ownerrez_source.call_args.kwargs["db_incremental_field_last_value"] is None
