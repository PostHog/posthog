import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hoorayhr import (
    HoorayHRSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.source import HoorayHRSource


class TestHoorayHRSource:
    def setup_method(self) -> None:
        self.source = HoorayHRSource()
        self.team_id = 123
        self.config = HoorayHRSourceConfig(api_key="pk_test_key")

    def test_canonical_descriptions_keyed_by_endpoint_names(self) -> None:
        # A renamed endpoint would silently orphan its curated descriptions.
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "valid_creds, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "HoorayHR rejected the credentials. Check the API key is correct and hasn't been revoked."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.source.validate_hoorayhr_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        valid_creds: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = valid_creds
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with("pk_test_key")
