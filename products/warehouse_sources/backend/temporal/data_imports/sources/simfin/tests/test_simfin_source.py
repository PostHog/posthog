from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.source import SimFinSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.simfin.source"


def _make_config(api_key: str = "key", tickers: str = "AAPL, MSFT") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.tickers = tickers
    return config


class TestSimFinSource:
    @parameterized.expand(
        [
            ("valid", "KEY", "AAPL", True, True, None),
            ("invalid_key", "KEY", "AAPL", False, False, "Invalid SimFin API key"),
            ("no_tickers", "KEY", "  ", True, False, "Enter at least one ticker (e.g. AAPL, MSFT)"),
            (
                "too_many_tickers",
                "KEY",
                ",".join(f"T{i}" for i in range(101)),
                True,
                False,
                "Too many tickers (101); enter at most 100 distinct tickers.",
            ),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        api_key: str,
        tickers: str,
        probe_result: bool,
        expected_ok: bool,
        expected_message: str | None,
    ) -> None:
        with patch(f"{MODULE}.validate_simfin_credentials", return_value=probe_result):
            ok, message = SimFinSource().validate_credentials(_make_config(api_key, tickers), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    def test_validate_credentials_skips_probe_without_tickers(self) -> None:
        # No point probing the API key if there are no tickers to sync — fail fast on tickers first.
        with patch(f"{MODULE}.validate_simfin_credentials") as probe:
            ok, _ = SimFinSource().validate_credentials(_make_config(tickers=""), team_id=1)
        assert ok is False
        probe.assert_not_called()

    def test_source_for_pipeline_plumbs_tickers_key_and_version(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "share_prices"
        inputs.api_version = None
        inputs.logger = MagicMock()
        with patch(f"{MODULE}.simfin_source") as source_fn:
            SimFinSource().source_for_pipeline(_make_config("abc", "aapl, msft"), inputs)
        source_fn.assert_called_once()
        kwargs = source_fn.call_args.kwargs
        assert kwargs["api_key"] == "abc"
        # Tickers are parsed (upper-cased, de-duplicated) before handing off to the transport.
        assert kwargs["tickers"] == ["AAPL", "MSFT"]
        assert kwargs["endpoint"] == "share_prices"
        # An unpinned source resolves to the default vendor API version.
        assert kwargs["api_version"] == "v3"

    def test_source_for_pipeline_rejects_oversized_ticker_list(self) -> None:
        # A previously-saved oversized config must fail the run instead of fanning out into a runaway sync.
        inputs = MagicMock()
        inputs.schema_name = "share_prices"
        inputs.logger = MagicMock()
        oversized = _make_config("abc", ",".join(f"T{i}" for i in range(101)))
        with patch(f"{MODULE}.simfin_source") as source_fn:
            with pytest.raises(ValueError, match="Too many tickers"):
                SimFinSource().source_for_pipeline(oversized, inputs)
        source_fn.assert_not_called()

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://backend.simfin.com"),
            ("forbidden", "403 Client Error: Forbidden for url: https://backend.simfin.com"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = SimFinSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]
