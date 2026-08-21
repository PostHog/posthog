from typing import cast

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    EZOFFICEINVENTORY_API_VERSION_V1,
    EZOFFICEINVENTORY_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.source import (
    EZOfficeInventorySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ezofficeinventory import (
    EZOfficeInventorySourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.source"


def _config() -> EZOfficeInventorySourceConfig:
    return cast(EZOfficeInventorySourceConfig, EZOfficeInventorySourceConfig(subdomain="acme", api_key="tok"))


class TestSourceVersions:
    def test_v2_is_the_default(self) -> None:
        # New sources are stamped with default_version; the whole point of this bump is that they
        # land on v2 while existing v1 pins are untouched.
        source = EZOfficeInventorySource()
        assert source.default_version == EZOFFICEINVENTORY_API_VERSION_V2
        assert source.supported_versions == (EZOFFICEINVENTORY_API_VERSION_V1, EZOFFICEINVENTORY_API_VERSION_V2)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("transport_result", "expected_ok"),
        [((True, None), True), ((False, None), False)],
    )
    def test_delegates_to_transport(self, transport_result: tuple[bool, str | None], expected_ok: bool) -> None:
        with patch(f"{_MODULE}.validate_ezofficeinventory_credentials", return_value=transport_result) as mocked:
            ok, error = EZOfficeInventorySource().validate_credentials(_config(), team_id=1)
        # No pin resolves to the default version, so the probe runs under v2.
        mocked.assert_called_once_with("tok", "acme", EZOFFICEINVENTORY_API_VERSION_V2)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_surfaces_transport_error_message(self) -> None:
        with patch(
            f"{_MODULE}.validate_ezofficeinventory_credentials",
            return_value=(False, "EZOfficeInventory rate limit reached while validating credentials."),
        ):
            ok, error = EZOfficeInventorySource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error == "EZOfficeInventory rate limit reached while validating credentials."
