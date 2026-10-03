from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.source import KalshiSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.source"


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "trades",
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


class TestKalshiSource:
    @parameterized.expand(
        [
            ("trades_is_incremental", "trades", True),
            ("markets_is_not", "markets", False),
            ("events_is_not", "events", False),
            ("series_is_not", "series", False),
            ("milestones_is_not", "milestones", False),
        ]
    )
    def test_only_trades_supports_incremental(self, _name: str, endpoint: str, expected: bool) -> None:
        # Only /markets/trades honours a server-side time filter. Advertising incremental anywhere
        # else would promise a cheap sync that still walks the whole collection.
        schemas = {s.name: s for s in KalshiSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert schemas[endpoint].supports_incremental is expected

    @parameterized.expand([("reachable", True, True), ("unreachable", False, False)])
    @mock.patch(f"{SOURCE_MODULE}.validate_kalshi_credentials")
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: bool, mock_validate) -> None:
        mock_validate.return_value = probe_ok

        ok, message = KalshiSource().validate_credentials(None, 1)  # type: ignore[arg-type]

        assert ok is expected
        assert (message is None) is expected

    @mock.patch(f"{SOURCE_MODULE}.kalshi_source")
    def test_source_for_pipeline_drops_the_watermark_on_full_refresh(self, mock_source) -> None:
        # A stale watermark leaking into a full refresh would filter rows the user asked to re-import.
        inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value=123)

        KalshiSource().source_for_pipeline(None, mock.MagicMock(), inputs)  # type: ignore[arg-type]

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_is_visible_and_labelled_alpha(self) -> None:
        # unreleasedSource=True hides the connector from users entirely; this source is finished.
        config = KalshiSource().get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"
        assert config.category is not None
        assert config.iconPath == "/static/services/kalshi.png"
