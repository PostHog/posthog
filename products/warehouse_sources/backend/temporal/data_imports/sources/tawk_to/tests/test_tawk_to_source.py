import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tawkto import TawkToSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source import TawkToSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.tawk_to import (
    TawkToCredentialsError,
    TawkToRetryableError,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source"


class TestTawkToSource:
    def setup_method(self):
        self.source = TawkToSource()
        self.team_id = 123
        self.config = TawkToSourceConfig(api_key="api-key")

    @pytest.mark.parametrize(
        "side_effect, expected_valid, expected_message",
        [
            (None, True, None),
            (TawkToCredentialsError("rejected"), False, "rejected"),
            (TawkToRetryableError("status=503"), False, "couldn't reach tawk.to"),
            (requests.ConnectionError("boom"), False, "couldn't reach tawk.to"),
        ],
    )
    @mock.patch(f"{MODULE}.validate_tawk_to_credentials")
    def test_validate_credentials(self, mock_validate, side_effect, expected_valid, expected_message):
        mock_validate.side_effect = side_effect

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message is None:
            assert error_message is None
        else:
            assert expected_message in (error_message or "")
        mock_validate.assert_called_once_with(self.config.api_key)

    @pytest.mark.parametrize("raw_property_id", [None, "", "   "])
    @mock.patch(f"{MODULE}.tawk_to_source")
    def test_source_for_pipeline_normalizes_blank_property_id(self, mock_tawk_to_source, raw_property_id):
        inputs = mock.MagicMock()
        inputs.schema_name = "chats"
        config = TawkToSourceConfig(api_key="api-key", property_id=raw_property_id)

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        assert mock_tawk_to_source.call_args.kwargs["property_id"] is None
