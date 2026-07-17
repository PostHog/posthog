from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit import (
    ConvertKitResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.source import ConvertKitSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ConvertKitSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestConvertKitSource:
    def setup_method(self) -> None:
        self.source = ConvertKitSource()
        self.team_id = 123
        self.config = ConvertKitSourceConfig(api_key="kit_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CONVERTKIT

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "ConvertKit"
        assert config.label == "ConvertKit"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/convertkit.png"
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_subscribers_supports_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["subscribers"].supports_incremental is True
        assert {f["field"] for f in schemas["subscribers"].incremental_fields} == {"created_at", "updated_at"}
        for name, schema in schemas.items():
            if name != "subscribers":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["subscribers"])
        assert len(schemas) == 1
        assert schemas[0].name == "subscribers"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @parameterized.expand(
        [
            ("valid", (True, None), True, None),
            (
                "invalid",
                (False, "Invalid or insufficiently scoped Kit API key"),
                False,
                "Invalid or insufficiently scoped Kit API key",
            ),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.source.validate_convertkit_credentials"
    )
    def test_validate_credentials(self, _name, mock_return, expected_valid, expected_message, mock_validate) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, None)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.source.validate_convertkit_credentials"
    )
    def test_validate_credentials_passes_schema_name(self, mock_validate) -> None:
        mock_validate.return_value = (True, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="subscribers")
        mock_validate.assert_called_once_with(self.config.api_key, "subscribers")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.kit.com",),
            ("403 Client Error: Forbidden for url: https://api.kit.com",),
        ]
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",),
            ("403 Client Error: Forbidden for url: https://api.clerk.com/v1/users",),
        ]
    )
    def test_non_retryable_errors_do_not_match_other_vendors(self, other_vendor_error: str) -> None:
        assert not any(key in other_vendor_error for key in self.source.get_non_retryable_errors())

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ConvertKitResumeConfig

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.source.convertkit_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_source) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "subscribers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "created_at"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "kit_test"
        assert kwargs["endpoint"] == "subscribers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "created_at"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.source.convertkit_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_source) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "tags"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
