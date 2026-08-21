from typing import Any, cast

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source import FilloutSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fillout import (
    FilloutSourceConfig,
)


class TestFilloutSource:
    def setup_method(self) -> None:
        self.source = FilloutSource()
        self.team_id = 123
        self.config = FilloutSourceConfig(api_key="fillout-key")

    def test_validate_credentials_rejects_unknown_api_base_url(self) -> None:
        config = FilloutSourceConfig(api_key="fillout-key", api_base_url=cast(Any, "https://api.fillout.com"))
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "API base URL must be one of" in message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source.validate_fillout_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="submissions")

        assert result == (True, None)
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["api_key"] == "fillout-key"
        assert kwargs["api_base_url"] == "https://api.fillout.com/v1/api"
        assert kwargs["schema_name"] == "submissions"
