import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source import BraintreeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braintree import (
    BraintreeSourceConfig,
)


class TestBraintreeSource:
    def setup_method(self):
        self.source = BraintreeSource()
        self.team_id = 123
        self.config = BraintreeSourceConfig(environment="production", public_key="pub", private_key="priv")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Braintree API keys"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source.validate_braintree_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("production", "pub", "priv", "2026-10-06")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source.braintree_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_bt_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bt_source.assert_called_once()
        kwargs = mock_bt_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["public_key"] == "pub"
        assert kwargs["private_key"] == "priv"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    def test_supported_versions_and_default(self):
        assert self.source.supported_versions == ("2019-01-01", "2026-07-14", "2026-08-04", "2026-08-13", "2026-10-06")
        # New sources start on the latest version; the default must stay in supported.
        assert self.source.default_version == "2026-10-06"
        assert self.source.default_version in self.source.supported_versions

    @pytest.mark.parametrize(
        "pinned, expected",
        [
            ("2019-01-01", "2019-01-01"),
            ("2026-07-14", "2026-07-14"),
            ("2026-08-04", "2026-08-04"),
            ("2026-08-13", "2026-08-13"),
            ("2026-10-06", "2026-10-06"),
            (None, "2026-10-06"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source.braintree_source")
    def test_source_for_pipeline_dispatches_resolved_version(self, mock_bt_source, pinned, expected):
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = False
        inputs.api_version = pinned

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_bt_source.call_args.kwargs["api_version"] == expected
