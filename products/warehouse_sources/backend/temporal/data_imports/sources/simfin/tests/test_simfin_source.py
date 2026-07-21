from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.source import SimFinSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.simfin.source"


def _make_config(api_key: str = "key", tickers: str = "AAPL, MSFT") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.tickers = tickers
    return config


class TestSimFinSource:
    def test_source_type(self) -> None:
        assert SimFinSource().source_type == ExternalDataSourceType.SIMFIN

    def test_source_config_has_api_key_and_tickers_fields(self) -> None:
        config = SimFinSource().get_source_config
        assert [f.name for f in config.fields] == ["api_key", "tickers"]
        api_key_field, tickers_field = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        # The API key is a secret credential, so it must render as a password input.
        assert api_key_field.type == "password"
        assert api_key_field.secret is True
        assert api_key_field.required is True
        # Tickers are not secret and drive the per-ticker fan-out.
        assert isinstance(tickers_field, SourceFieldInputConfig)
        assert tickers_field.type == "text"
        assert tickers_field.secret is False
        assert tickers_field.required is True

    def test_source_config_is_released_as_alpha(self) -> None:
        config = SimFinSource().get_source_config
        # unreleasedSource hides the connector entirely; a finished source must ship visible.
        assert not config.unreleasedSource
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/simfin"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert SimFinSource.lists_tables_without_credentials is True

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = SimFinSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # SimFin has no server-side change cursor, so nothing supports incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_exposes_primary_keys(self) -> None:
        schemas = {s.name: s for s in SimFinSource().get_schemas(_make_config(), team_id=1)}
        assert schemas["companies"].detected_primary_keys == ["id"]
        assert schemas["income_statements"].detected_primary_keys == ["id", "fiscal_year", "fiscal_period"]
        assert schemas["share_prices"].detected_primary_keys == ["id", "date"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = SimFinSource().get_schemas(_make_config(), team_id=1, names=["companies", "share_prices"])
        assert {s.name for s in schemas} == {"companies", "share_prices"}

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

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = SimFinSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "income_statements" in descriptions
        assert "share_prices" in descriptions
