import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ProductboardSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard import (
    ProductboardResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.source import (
    ProductboardSource,
    _probe_path,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestProductboardSource:
    def setup_method(self):
        self.source = ProductboardSource()
        self.team_id = 123
        self.config = ProductboardSourceConfig(access_token="pb-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PRODUCTBOARD

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Productboard"
        assert config.label == "Productboard"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/productboard.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.productboard.com/v2/notes",
            "403 Client Error: Forbidden for url: https://api.productboard.com/v2/entities?type[]=feature",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.productboard.com/v2/notes",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_notes_supports_incremental(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == {"notes"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["notes"].incremental_fields == INCREMENTAL_FIELDS["notes"]
        assert {f["field"] for f in schemas["notes"].incremental_fields} == {"createdAt", "updatedAt"}
        assert schemas["features"].incremental_fields == []
        assert schemas["features"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["notes"])
        assert len(schemas) == 1
        assert schemas[0].name == "notes"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "probe_return, schema_name, expected_valid, expected_message",
        [
            ((True, 200, None), None, True, None),
            ((False, 401, "Unauthorized"), None, False, "Invalid Productboard access token"),
            # 403 at source-create means a valid token that just lacks scope for the probe endpoint.
            ((False, 403, "Forbidden"), None, True, None),
            # 403 on a specific schema means the user can't sync that endpoint.
            ((False, 403, "Forbidden"), "notes", False, "Forbidden"),
            ((False, 500, "Server error"), None, False, "Server error"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.source.validate_productboard_credentials"
    )
    def test_validate_credentials(self, mock_validate, probe_return, schema_name, expected_valid, expected_message):
        mock_validate.return_value = probe_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        assert error_message == expected_message

    @pytest.mark.parametrize(
        "schema_name, expected_path",
        [
            (None, "/members"),
            ("features", "/entities?type[]=feature"),
            ("key_results", "/entities?type[]=keyResult"),
            ("notes", "/notes"),
            ("members", "/members"),
            ("teams", "/teams"),
        ],
    )
    def test_probe_path(self, schema_name, expected_path):
        assert _probe_path(schema_name) == expected_path

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ProductboardResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.source.productboard_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_productboard_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "notes"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2023-10-01T00:00:00Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_productboard_source.assert_called_once()
        kwargs = mock_productboard_source.call_args.kwargs
        assert kwargs["access_token"] == "pb-token"
        assert kwargs["endpoint"] == "notes"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2023-10-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.source.productboard_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_productboard_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "features"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2023-10-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_productboard_source.call_args.kwargs["db_incremental_field_last_value"] is None
