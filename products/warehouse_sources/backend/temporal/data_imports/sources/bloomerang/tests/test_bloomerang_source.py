import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.bloomerang import BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.source import BloomerangSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bloomerang import (
    BloomerangSourceConfig,
)

_INCREMENTAL_ENDPOINTS = {"Constituents"}
_FULL_REFRESH_ENDPOINTS = {"Transactions", "Interactions", "Appeals", "Campaigns", "Funds"}


class TestBloomerangSource:
    def setup_method(self):
        self.source = BloomerangSource()
        self.team_id = 123
        self.config = BloomerangSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.bloomerang.co/v2/constituents?skip=0&take=50",
            "403 Client Error: Forbidden for url: https://api.bloomerang.co/v2/transactions?skip=0&take=50",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.bloomerang.co/v2/constituents",
            "500 Server Error: Internal Server Error for url: https://api.bloomerang.co/v2/constituents",
            "HTTPSConnectionPool(host='api.bloomerang.co', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Bloomerang API key"),
            ((False, 403), False, "Could not connect to Bloomerang with the provided API key"),
            ((False, None), False, "Could not connect to Bloomerang with the provided API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.source.validate_bloomerang_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    @pytest.mark.parametrize(
        "pinned, expected_version",
        [("v1", "v1"), ("v2", None), (None, None)],
    )
    def test_deprecation_flags_legacy_v1_only(self, pinned, expected_version):
        deprecation = self.source.get_version_deprecation(pinned)
        if expected_version is None:
            assert deprecation is None
        else:
            assert deprecation is not None
            assert deprecation.version == expected_version
            assert deprecation.sunset_at is None  # vendor published no sunset date

    def test_request_layer_stays_on_the_v2_wire(self):
        # No per-version dispatch: `/v2` is a fixed path segment, so a legacy v1 pin rides the same
        # wire as v2. Regressing this URL to v1 would move every v1-pinned source onto the vendor's
        # deprecated API.
        assert BASE_URL == "https://api.bloomerang.co/v2"
