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

    def test_resolve_api_version_falls_back_to_default_and_honors_pin(self):
        assert self.source.resolve_api_version(None) == BREX_API_VERSION_V2
        assert self.source.resolve_api_version(BREX_API_VERSION_V1) == BREX_API_VERSION_V1

    def test_v1_is_deprecated_without_sunset_and_v2_is_not(self):
        # Brex announced no sunset date, so v1 is flagged deprecated with sunset_at=None; the default
        # v2 must never be deprecated.
        deprecation = self.source.get_version_deprecation(BREX_API_VERSION_V1)
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert self.source.get_version_deprecation(BREX_API_VERSION_V2) is None

    def test_non_retryable_401_message_mentions_token_expiry(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        message = non_retryable_errors["401 Client Error: Unauthorized for url: https://api.brex.com"]
        assert message is not None
        assert "90 days" in message

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
