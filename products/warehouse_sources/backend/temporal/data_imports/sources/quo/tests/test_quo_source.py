import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.quo import QuoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.source import QuoSource


class TestQuoSource:
    def setup_method(self):
        self.source = QuoSource()
        self.team_id = 123
        self.config = QuoSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "mock_return, api_version, expected_valid, expected_message, expected_version",
        [
            (True, None, True, None, "2026-03-30"),
            (True, "v1", True, None, "v1"),
            (False, None, False, "Invalid Quo API key", "2026-03-30"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.quo.source.validate_quo_credentials")
    def test_validate_credentials(
        self, mock_validate, mock_return, api_version, expected_valid, expected_message, expected_version
    ):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, api_version=api_version)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, expected_version)

    @pytest.mark.parametrize(
        "pinned_version, expected_version",
        [
            (None, "2026-03-30"),
            ("v1", "v1"),
            ("2026-03-30", "2026-03-30"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.quo.source.quo_source")
    def test_source_for_pipeline_passes_resolved_version(self, mock_quo_source, pinned_version, expected_version):
        inputs = mock.MagicMock(api_version=pinned_version)

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_quo_source.call_args.kwargs["api_version"] == expected_version
