import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.adjust import (
    AdjustCredentialsError,
    AdjustRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.source import AdjustSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adjust import AdjustSourceConfig

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adjust.source"


class TestAdjustSource:
    def setup_method(self) -> None:
        self.source = AdjustSource()
        self.team_id = 123
        self.config = AdjustSourceConfig(api_token="adjust-token", app_tokens="abc123")

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    @mock.patch(f"{_SOURCE_MODULE}.validate_adjust_credentials")
    def test_validate_credentials_success(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        mock_validate.assert_called_once_with("adjust-token", "abc123")

    @mock.patch(f"{_SOURCE_MODULE}.validate_adjust_credentials")
    def test_validate_credentials_surfaces_the_specific_rejection(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = AdjustCredentialsError("Adjust rejected the API token.")

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message == "Adjust rejected the API token."

    @pytest.mark.parametrize(
        "raised",
        [AdjustRetryableError("status=503"), requests.ConnectionError("boom"), requests.ReadTimeout("slow")],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_adjust_credentials")
    def test_transient_failures_are_not_reported_as_bad_credentials(
        self, mock_validate: mock.MagicMock, raised: Exception
    ) -> None:
        mock_validate.side_effect = raised

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None
        assert "temporary rate-limit or network issue" in message
