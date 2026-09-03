from typing import Any

from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.source import AirwallexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.source"


class _Config:
    client_id = "cid"
    api_key = "key"
    environment = "live"


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "FinancialTransactions",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestAirwallexSource:
    @parameterized.expand(
        [
            ("settlements_track_settled_at", "Settlements", "settled_at"),
            ("beneficiaries_track_created_at", "Beneficiaries", "created_at"),
            ("transactions_track_created_at", "FinancialTransactions", "created_at"),
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

    @mock.patch(f"{SOURCE_MODULE}.airwallex_source")
    def test_source_for_pipeline_passes_the_watermark_when_incremental(self, mock_source) -> None:
        inputs = _inputs(should_use_incremental_field=True, db_incremental_field_last_value=123)

        AirwallexSource().source_for_pipeline(_Config(), mock.MagicMock(), inputs)  # type: ignore[arg-type]

        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "FinancialTransactions"
        assert kwargs["db_incremental_field_last_value"] == 123
        assert kwargs["environment"] == "live"

    @mock.patch(f"{SOURCE_MODULE}.airwallex_source")
    def test_source_for_pipeline_drops_the_watermark_on_full_refresh(self, mock_source) -> None:
        # A stale watermark leaking into a full refresh would filter out rows the user asked to re-import.
        inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value=123)

        AirwallexSource().source_for_pipeline(_Config(), mock.MagicMock(), inputs)  # type: ignore[arg-type]

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @parameterized.expand([("stored_pin_wins", "2025-06-30", "2025-06-30"), ("no_pin_defaults", None, "2026-07-17")])
    @mock.patch(f"{SOURCE_MODULE}.airwallex_source")
    def test_source_for_pipeline_resolves_the_api_version(
        self, _name: str, pinned: str | None, expected: str, mock_source
    ) -> None:
        # A source created against an older version must keep calling that version.
        inputs = _inputs(api_version=pinned)

        AirwallexSource().source_for_pipeline(_Config(), mock.MagicMock(), inputs)  # type: ignore[arg-type]

        assert mock_source.call_args.kwargs["api_version"] == expected

    def test_source_is_visible_and_labelled_alpha(self) -> None:
        # unreleasedSource=True hides the connector from users entirely; this source is finished.
        config = AirwallexSource().get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"
        assert config.category is not None
        assert config.iconPath == "/static/services/airwallex.png"

    def test_the_api_key_field_is_marked_secret(self) -> None:
        # A non-secret credential field is stored and returned in the clear by the serializer.
        fields = {f.name: f for f in AirwallexSource().get_source_config.fields}
        api_key = fields["api_key"]

        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
