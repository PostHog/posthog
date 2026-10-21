from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.marketstack import (
    MarketstackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack import (
    MARKETSTACK_API_VERSION_V1,
    MARKETSTACK_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source import MarketstackSource


def _make_config(access_key: str = "key", symbols: str | None = "AAPL") -> MarketstackSourceConfig:
    return MarketstackSourceConfig(access_key=access_key, symbols=symbols)


class TestMarketstackSource:
    @parameterized.expand(
        [
            ("legacy_v1_pin_hides_v2_only_tables", MARKETSTACK_API_VERSION_V1, False),
            ("v2_pin_lists_v2_only_tables", MARKETSTACK_API_VERSION_V2, True),
            ("no_pin_resolves_to_v2", None, True),
        ]
    )
    def test_get_schemas_lists_v2_only_tables_by_pin(self, _name: str, pin: str | None, expected: bool) -> None:
        names = {s.name for s in MarketstackSource().get_schemas(_make_config(), team_id=1, api_version=pin)}
        assert "eod" in names
        assert (
            {"tickerinfo", "companyratings", "submissions"} <= names
            if expected
            else not ({"tickerinfo", "companyratings", "submissions"} & names)
        )

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Marketstack access key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, expected_message: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.source.validate_marketstack_credentials",
            return_value=probe_result,
        ) as probe:
            ok, message = MarketstackSource().validate_credentials(_make_config(), team_id=1)
        assert ok is expected_ok
        assert message == expected_message
        # A pre-creation probe (no pin) resolves to the default version the new row is stamped with.
        assert probe.call_args.args[1] == MARKETSTACK_API_VERSION_V2

    def test_source_for_pipeline_plumbs_symbols_and_keys(self) -> None:
        result = SourceDriver(MarketstackSource(), _make_config("abc", "AAPL,MSFT")).run(
            "eod",
            [ScriptedResponse(json={"data": [], "pagination": {"total": 0}})],
            db_incremental_field_last_value="2021-04-09",
            should_use_incremental_field=True,
            api_version=MARKETSTACK_API_VERSION_V2,
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "eod"
        assert result.response.primary_keys == ["symbol", "exchange", "date"]
        assert result.requests[0].param("symbols") == "AAPL,MSFT"
        assert result.requests[0].param("access_key") == "abc"
        assert result.requests[0].param("date_from") == "2021-04-09"

    @parameterized.expand(
        [
            ("no_pin_resolves_to_default", None, MARKETSTACK_API_VERSION_V2),
            ("legacy_pin_honored", MARKETSTACK_API_VERSION_V1, MARKETSTACK_API_VERSION_V1),
            ("new_pin_honored", MARKETSTACK_API_VERSION_V2, MARKETSTACK_API_VERSION_V2),
        ]
    )
    def test_source_for_pipeline_threads_resolved_version(self, _name: str, pin: str | None, expected: str) -> None:
        result = SourceDriver(MarketstackSource(), _make_config()).run(
            "eod", [ScriptedResponse(json={"data": [], "pagination": {"total": 0}})], api_version=pin
        )

        assert result.raised is None
        assert result.requests[0].path == f"/{expected}/eod"

    @parameterized.expand(
        [
            ("body_invalid_key", "Marketstack API error [invalid_access_key]"),
            ("body_usage_limit", "Marketstack API error [usage_limit_reached]"),
            ("body_function_restricted", "Marketstack API error [function_access_restricted]"),
            ("body_missing_symbols", "Marketstack API error [missing_symbols]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = MarketstackSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]
