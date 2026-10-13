import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex import (
    BREX_API_VERSION_V1,
    BREX_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.source import BrexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.brex import BrexSourceConfig


class TestBrexSource:
    def setup_method(self):
        self.source = BrexSource()
        self.team_id = 123
        self.config = BrexSourceConfig(api_key="bxt_test_token")

    def test_supported_versions_and_default(self):
        # New sources are stamped with the default; v1 stays supported so existing pins keep working.
        assert self.source.supported_versions == (BREX_API_VERSION_V1, BREX_API_VERSION_V2)
        assert self.source.default_version == BREX_API_VERSION_V2

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.validate_brex_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_valid:
            assert error_message is None
        else:
            assert error_message is not None
            assert "90 days" in error_message
        mock_validate.assert_called_once_with(self.config.api_key)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.brex_source")
    def test_source_for_pipeline_passes_pinned_api_version(self, mock_brex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.api_version = BREX_API_VERSION_V1

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_brex_source.call_args.kwargs["api_version"] == BREX_API_VERSION_V1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.brex_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_brex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_brex_source.call_args.kwargs["db_incremental_field_last_value"] is None
