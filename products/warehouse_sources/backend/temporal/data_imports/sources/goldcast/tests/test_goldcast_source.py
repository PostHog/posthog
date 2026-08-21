from typing import Any

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import GOLDCAST_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source import GoldcastSource


def _config(access_key: str = "tok") -> Any:
    config = MagicMock()
    config.access_key = access_key
    return config


class TestGetSchemas:
    def test_detected_primary_keys_match_settings(self) -> None:
        schemas = {s.name: s for s in GoldcastSource().get_schemas(_config(), team_id=1)}
        for name, config in GOLDCAST_ENDPOINTS.items():
            assert schemas[name].detected_primary_keys == config.primary_keys


class TestValidateCredentials:
    def test_valid_token_passes(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source.validate_goldcast_credentials",
            return_value=True,
        ):
            assert GoldcastSource().validate_credentials(_config(), team_id=1) == (True, None)

    def test_invalid_token_surfaces_message(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source.validate_goldcast_credentials",
            return_value=False,
        ):
            valid, message = GoldcastSource().validate_credentials(_config(), team_id=1)
        assert valid is False
        assert message == "Invalid Goldcast API token"
