import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GongSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong import GongResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.source import GongSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGongSource:
    def setup_method(self):
        self.source = GongSource()
        self.team_id = 123
        self.config = GongSourceConfig(access_key="key", access_key_secret="secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GONG

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Gong"
        assert config.label == "Gong"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/gong.png"

        fields = config.fields
        assert len(fields) == 2

        access_key_field, secret_field = fields
        assert isinstance(access_key_field, SourceFieldInputConfig)
        assert access_key_field.name == "access_key"
        assert access_key_field.type == SourceFieldInputConfigType.TEXT
        assert access_key_field.required is True

        assert isinstance(secret_field, SourceFieldInputConfig)
        assert secret_field.name == "access_key_secret"
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.required is True
        assert secret_field.secret is True

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # Only `calls` exposes a server-side timestamp filter.
        assert schemas["calls"].supports_incremental is True
        assert schemas["calls"].supports_append is True
        assert any(f["field"] == "started" for f in schemas["calls"].incremental_fields)

        for name in ("users", "scorecards", "workspaces"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])

        assert len(schemas) == 1
        assert schemas[0].name == "calls"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            (
                (False, "Invalid Gong access key or access key secret"),
                False,
                "Invalid Gong access key or access key secret",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gong.source.validate_gong_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_key, self.config.access_key_secret, None)

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.gong.io",
            "403 Client Error: Forbidden for url: https://api.gong.io",
        ],
    )
    def test_non_retryable_errors_includes_gong_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "403 Client Error: Forbidden for url: https://api.klaviyo.com/api/accounts",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GongResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.source.gong_source"
        ) as mock_gong_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_gong_source.assert_called_once()
        kwargs = mock_gong_source.call_args.kwargs
        assert kwargs["access_key"] == "key"
        assert kwargs["access_key_secret"] == "secret"
        assert kwargs["endpoint"] == "calls"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_omits_last_value_on_full_refresh(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.source.gong_source"
        ) as mock_gong_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_gong_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
