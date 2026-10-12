import pytest
from unittest import mock

from sources.bloomerang._config import BloomerangSourceConfig
from sources.bloomerang.bloomerang import BASE_URL
from sources.bloomerang.source import BloomerangSource

_INCREMENTAL_ENDPOINTS = {"Constituents"}
_FULL_REFRESH_ENDPOINTS = {"Transactions", "Interactions", "Appeals", "Campaigns", "Funds"}


class TestBloomerangSource:
    def setup_method(self):
        self.source = BloomerangSource()
        self.team_id = 123
        self.config = BloomerangSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Bloomerang API key"),
            ((False, 403), False, "Could not connect to Bloomerang with the provided API key"),
            ((False, None), False, "Could not connect to Bloomerang with the provided API key"),
        ],
    )
    @mock.patch("sources.bloomerang.source.validate_bloomerang_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    def test_request_layer_stays_on_the_v2_wire(self):
        # No per-version dispatch: `/v2` is a fixed path segment, so a legacy v1 pin rides the same
        # wire as v2. Regressing this URL to v1 would move every v1-pinned source onto the vendor's
        # deprecated API.
        assert BASE_URL == "https://api.bloomerang.co/v2"
