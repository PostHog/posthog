from typing import Any

from unittest import mock

import structlog
from parameterized import parameterized

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twelvedata import (
    TwelveDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.source import TwelveDataSource


def _config(**overrides: Any) -> TwelveDataSourceConfig:
    values: dict[str, Any] = {"api_key": "key", "symbols": "AAPL, MSFT"}
    values.update(overrides)
    return TwelveDataSourceConfig(**values)


def _inputs(
    schema_name: str,
    should_use_incremental: bool = False,
    last_value: Any = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental,
        db_incremental_field_last_value=last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="datetime",
        incremental_field_type=None,
        job_id="job-1",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestTwelveDataSource:
    def setup_method(self) -> None:
        self.source = TwelveDataSource()

    def test_source_is_released_as_alpha(self) -> None:
        # unreleasedSource hides the connector from every user — a finished source must not carry it.
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

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

    def test_source_for_pipeline_plumbs_config(self) -> None:
        inputs = _inputs("time_series", should_use_incremental=True, last_value="2026-07-01")
        manager = mock.MagicMock()
        with mock.patch.object(source_module, "twelve_data_source") as transport:
            self.source.source_for_pipeline(_config(start_date=" 2020-01-01 "), manager, inputs)

        transport.assert_called_once_with(
            api_key="key",
            endpoint="time_series",
            symbols=["AAPL", "MSFT"],
            interval="1day",
            config_start_date="2020-01-01",
            resumable_source_manager=manager,
            logger=inputs.logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01",
        )

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # A stale watermark from a previous incremental setup must not bound a full refresh.
        inputs = _inputs("time_series", should_use_incremental=False, last_value="2026-07-01")
        with mock.patch.object(source_module, "twelve_data_source") as transport:
            self.source.source_for_pipeline(_config(), mock.MagicMock(), inputs)
        assert transport.call_args.kwargs["db_incremental_field_last_value"] is None
        assert transport.call_args.kwargs["config_start_date"] is None

    def test_auth_and_symbol_errors_are_non_retryable(self) -> None:
        # Without these, a revoked key or a typoed symbol retries forever.
        non_retryable = self.source.get_non_retryable_errors()
        for code in (401, 403, 404):
            assert any(f"Twelve Data API error {code}" in key for key in non_retryable)
