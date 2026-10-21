import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ownerrez import (
    OwnerrezSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source import OwnerrezSource

_INCREMENTAL_ENDPOINTS = {"Bookings", "Quotes", "Reviews"}
_FULL_REFRESH_ENDPOINTS = {"Payments", "Guests", "Properties", "Deposits", "Fees", "Refunds"}


class TestOwnerrezSource:
    def setup_method(self):
        self.source = OwnerrezSource()
        self.team_id = 123
        self.config = OwnerrezSourceConfig(email="host@example.com", api_key="pt_key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid OwnerRez account email or personal access token"),
            (
                (False, 403),
                False,
                "Could not connect to OwnerRez with the provided account email and personal access token",
            ),
            (
                (False, None),
                False,
                "Could not connect to OwnerRez with the provided account email and personal access token",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source.validate_ownerrez_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("host@example.com", "pt_key")
