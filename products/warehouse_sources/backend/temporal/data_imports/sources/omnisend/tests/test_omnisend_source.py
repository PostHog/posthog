import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omnisend import (
    OmnisendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import (
    OMNISEND_2026_03_15,
    OMNISEND_V3,
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
        ("api_version", "expected_tables"),
        [
            (OMNISEND_V3, {"contacts", "campaigns", "carts", "orders", "products", "categories"}),
            (OMNISEND_2026_03_15, {"contacts", "campaigns", "products", "categories"}),
            (None, {"contacts", "campaigns", "products", "categories"}),
        ],
    )
    def test_schemas_follow_the_pinned_version(self, api_version: str | None, expected_tables: set[str]) -> None:
        schemas = OmnisendSource().get_schemas(_config(), team_id=1, api_version=api_version)
        assert {schema.name for schema in schemas} == expected_tables

    @pytest.mark.parametrize(
        ("api_version", "expected_version"),
        [(OMNISEND_V3, OMNISEND_V3), (OMNISEND_2026_03_15, OMNISEND_2026_03_15), (None, OMNISEND_2026_03_15)],
    )
    def test_validate_credentials_probes_the_pinned_version(
        self, api_version: str | None, expected_version: str
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.source.validate_omnisend_credentials",
            return_value=(True, 200),
        ) as probe:
            OmnisendSource().validate_credentials(_config(), team_id=1, api_version=api_version)
        probe.assert_called_once_with("test-key", expected_version)

    @pytest.mark.parametrize(
        ("api_version", "schema_name", "expected_ok"),
        [
            (OMNISEND_2026_03_15, "orders", False),
            (OMNISEND_V3, "orders", True),
            (OMNISEND_2026_03_15, "contacts", True),
        ],
    )
    def test_validate_credentials_rejects_tables_the_version_does_not_serve(
        self, api_version: str, schema_name: str, expected_ok: bool
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.source.validate_omnisend_credentials",
            return_value=(True, 200),
        ):
            ok, _ = OmnisendSource().validate_credentials(
                _config(), team_id=1, schema_name=schema_name, api_version=api_version
            )
        assert ok is expected_ok

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
