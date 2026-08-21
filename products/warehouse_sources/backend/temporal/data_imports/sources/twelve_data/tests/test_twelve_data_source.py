from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twelvedata import (
    TwelveDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.source import TwelveDataSource


def _config(**overrides: Any) -> TwelveDataSourceConfig:
    values: dict[str, Any] = {"api_key": "key", "symbols": "AAPL, MSFT"}
    values.update(overrides)
    return TwelveDataSourceConfig(**values)


class TestTwelveDataSource:
    def setup_method(self) -> None:
        self.source = TwelveDataSource()

    @parameterized.expand(
        [
            ("valid", "AAPL", (True, None), True, None),
            (
                "bad_key",
                "AAPL",
                (False, "Twelve Data API error 401: bad key"),
                False,
                "Twelve Data API error 401: bad key",
            ),
        ]
    )
    def test_validate_credentials_delegates_to_probe(
        self,
        _name: str,
        symbols: str,
        probe_result: tuple[bool, str | None],
        expected_ok: bool,
        expected_error: str | None,
    ) -> None:
        with mock.patch.object(source_module, "validate_twelve_data_credentials", return_value=probe_result):
            ok, error = self.source.validate_credentials(_config(symbols=symbols), team_id=1)
        assert ok is expected_ok
        assert error == expected_error

    def test_validate_credentials_requires_a_symbol(self) -> None:
        with mock.patch.object(source_module, "validate_twelve_data_credentials") as probe:
            ok, error = self.source.validate_credentials(_config(symbols="  , "), team_id=1)
        assert ok is False
        assert error == "Enter at least one symbol to sync"
        probe.assert_not_called()

    def test_validate_credentials_rejects_too_many_symbols(self) -> None:
        # Guards the fan-out cap: every per-symbol table issues one request per symbol.
        symbols = ",".join(f"S{i}" for i in range(source_module.MAX_SYMBOLS + 1))
        with mock.patch.object(source_module, "validate_twelve_data_credentials") as probe:
            ok, error = self.source.validate_credentials(_config(symbols=symbols), team_id=1)
        assert ok is False
        assert error == f"Too many symbols — the maximum is {source_module.MAX_SYMBOLS}"
        probe.assert_not_called()
