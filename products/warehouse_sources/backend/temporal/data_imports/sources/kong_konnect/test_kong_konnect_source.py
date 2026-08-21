from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kongkonnect import (
    KongKonnectSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.kong_konnect import (
    DEFAULT_INITIAL_LOOKBACK_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.source import (
    KongKonnectSource,
    _coerce_lookback_days,
)


def _config(**overrides: Any) -> KongKonnectSourceConfig:
    data = {"api_token": "kpat_test", "region": "us"}
    data.update(overrides)
    return KongKonnectSourceConfig.from_dict(data)


class TestValidateCredentials:
    @patch.object(source_module, "validate_kong_konnect_credentials", return_value=True)
    def test_valid(self, _mock: MagicMock) -> None:
        ok, err = KongKonnectSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert err is None

    @patch.object(source_module, "validate_kong_konnect_credentials", return_value=False)
    def test_invalid(self, _mock: MagicMock) -> None:
        ok, err = KongKonnectSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert err is not None

    def test_unknown_region_rejected_without_network(self) -> None:
        with patch.object(source_module, "validate_kong_konnect_credentials") as mock:
            ok, err = KongKonnectSource().validate_credentials(_config(region="mars"), team_id=1)
        assert ok is False
        assert err is not None
        mock.assert_not_called()


class TestCoerceLookbackDays:
    @parameterized.expand(
        [
            ("none", None, DEFAULT_INITIAL_LOOKBACK_DAYS),
            ("positive", 90, 90),
            ("zero", 0, DEFAULT_INITIAL_LOOKBACK_DAYS),
            ("negative", -3, DEFAULT_INITIAL_LOOKBACK_DAYS),
        ]
    )
    def test_coerce(self, _name: str, value: int | None, expected: int) -> None:
        assert _coerce_lookback_days(value) == expected


if __name__ == "__main__":
    pytest.main([__file__])
