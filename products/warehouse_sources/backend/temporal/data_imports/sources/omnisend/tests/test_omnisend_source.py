import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omnisend import (
    OmnisendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.source import OmnisendSource


def _config() -> OmnisendSourceConfig:
    return OmnisendSourceConfig(api_key="test-key")


class TestOmnisendSource:
    def test_all_endpoints_are_full_refresh(self) -> None:
        # We can't curl-verify Omnisend's server-side timestamp filter, so every endpoint
        # ships full refresh (no incremental advertised). See api_inventory.md.
        for schema in OmnisendSource().get_schemas(_config(), team_id=1):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        ("validate_return", "expected_ok", "expected_msg"),
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Omnisend API key"),
            ((False, 403), False, "Invalid Omnisend API key"),
            ((False, None), False, "Could not connect to Omnisend with the provided API key"),
            ((False, 500), False, "Could not connect to Omnisend with the provided API key"),
        ],
    )
    def test_validate_credentials(
        self, validate_return: tuple[bool, int | None], expected_ok: bool, expected_msg: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.source.validate_omnisend_credentials",
            return_value=validate_return,
        ):
            ok, msg = OmnisendSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg
