from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.source import AirwallexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airwallex import (
    AirwallexSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AirwallexSource(), AirwallexSourceConfig(client_id="cid", api_key="key", environment="live"))


class TestAirwallexSource:
    @parameterized.expand(
        [
            ("settlements_track_settled_at", "Settlements", "settled_at"),
            ("beneficiaries_track_created_at", "Beneficiaries", "created_at"),
            ("transactions_track_created_at", "FinancialTransactions", "created_at"),
            ("disputes_track_updated_at", "PaymentDisputes", "updated_at"),
        ]
    )
    def test_incremental_cursor_matches_the_field_the_filter_bounds(
        self, _name: str, endpoint: str, expected: str
    ) -> None:
        # Settlements filter on settled_at, everything else on created_at. Advertising the wrong
        # cursor would compare the watermark against a column the server never filtered.
        schemas = {s.name: s for s in AirwallexSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert schemas[endpoint].supports_incremental is True
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == [expected]

    def test_source_for_pipeline_passes_the_watermark_when_incremental(self) -> None:
        result = _driver().run(
            "FinancialTransactions",
            [ScriptedResponse(status=201, json={"token": "tok"}), ScriptedResponse(json={"items": []})],
            incremental_field="created_at",
            db_incremental_field_last_value=123,
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/authentication/login", "/api/v1/financial_transactions"]
        assert result.requests[1].param("from_created_at") == "1970-01-01T00:02:03Z"
        assert result.requests[1].origin == "https://api.airwallex.com"

    @parameterized.expand([("stored_pin_wins", "2025-06-30", "2025-06-30"), ("no_pin_defaults", None, "2026-07-17")])
    def test_source_for_pipeline_resolves_the_api_version(self, _name: str, pinned: str | None, expected: str) -> None:
        # A source created against an older version must keep calling that version.
        result = _driver().run(
            "FinancialTransactions",
            [ScriptedResponse(status=201, json={"token": "tok"}), ScriptedResponse(json={"items": []})],
            api_version=pinned,
        )

        assert result.raised is None
        assert result.requests[1].headers["x-api-version"] == expected

    def test_the_api_key_field_is_marked_secret(self) -> None:
        # A non-secret credential field is stored and returned in the clear by the serializer.
        fields = {f.name: f for f in AirwallexSource().get_source_config.fields}
        api_key = fields["api_key"]

        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
