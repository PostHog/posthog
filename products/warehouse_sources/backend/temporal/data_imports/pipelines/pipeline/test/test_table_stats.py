from unittest import mock

import pyarrow as pa
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.table_stats import (
    OUTLIER_TABLE_BYTES,
    record_source_item_stats,
    record_table_stats,
)

_STATS = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.table_stats.record_table_stats"
_BATCHER_STATS = (
    "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.record_table_stats"
)


class TestRecordTableStats:
    def test_safe_outside_activity_context(self):
        # The pipeline/batcher are constructed directly in unit tests, so this must not touch the
        # Temporal meter (which requires an activity) — it should simply no-op the metric.
        record_table_stats(
            source_type="Stripe", stage="batcher", num_rows=5, payload_bytes=100, logger=mock.MagicMock()
        )

    def test_records_metrics_inside_activity(self):
        # Exercises the real meter path (guards against a wrong create_histogram signature).
        ActivityEnvironment().run(
            lambda: record_table_stats(
                source_type="Stripe", stage="pipeline", num_rows=5, payload_bytes=100, logger=mock.MagicMock()
            )
        )

    def test_outlier_log_fires_at_threshold(self):
        logger = mock.MagicMock()
        record_table_stats(
            source_type="Stripe",
            stage="batcher",
            num_rows=10,
            payload_bytes=OUTLIER_TABLE_BYTES,
            logger=logger,
            team_id=7,
            schema_name="charges",
        )
        logger.warning.assert_called_once()
        assert logger.warning.call_args.args[0] == "data_import_large_table"
        assert logger.warning.call_args.kwargs["team_id"] == 7
        assert logger.warning.call_args.kwargs["schema_name"] == "charges"

    @parameterized.expand([("below_threshold", OUTLIER_TABLE_BYTES - 1), ("bytes_unknown", None)])
    def test_no_outlier_log(self, _name, payload_bytes):
        logger = mock.MagicMock()
        record_table_stats(
            source_type="Stripe", stage="pipeline", num_rows=10, payload_bytes=payload_bytes, logger=logger
        )
        logger.warning.assert_not_called()


class TestRecordSourceItemStats:
    def test_pa_table_reports_rows_and_bytes(self):
        item = pa.table({"a": [1, 2, 3], "s": ["xx", "yy", "zz"]})
        with mock.patch(_STATS) as recorded:
            record_source_item_stats(item, source_type="Stripe", logger=mock.MagicMock())
        kwargs = recorded.call_args.kwargs
        assert kwargs["stage"] == "pipeline"
        assert kwargs["num_rows"] == 3
        assert kwargs["payload_bytes"] is not None and kwargs["payload_bytes"] > 0

    @parameterized.expand(
        [
            ("list_of_rows", [{"a": 1}, {"a": 2}], 2),
            ("single_dict_row", {"a": 1}, 1),
        ]
    )
    def test_unmaterialized_item_reports_rows_only(self, _name, item, expected_rows):
        with mock.patch(_STATS) as recorded:
            record_source_item_stats(item, source_type="Stripe", logger=mock.MagicMock())
        kwargs = recorded.call_args.kwargs
        assert kwargs["num_rows"] == expected_rows
        # Arrow size is unknown before materialisation; the batcher stage records it instead.
        assert kwargs["payload_bytes"] is None


class TestBatcherStatsEmission:
    def test_emits_batcher_stage_when_source_type_set(self):
        with mock.patch(_BATCHER_STATS) as recorded:
            batcher = Batcher(logger=mock.MagicMock(), source_type="Stripe", team_id=1, schema_name="charges")
            batcher.batch(pa.table({"a": [1, 2, 3]}))
            batcher.get_table()
        recorded.assert_called_once()
        kwargs = recorded.call_args.kwargs
        assert kwargs["source_type"] == "Stripe"
        assert kwargs["stage"] == "batcher"
        assert kwargs["num_rows"] == 3
        assert kwargs["payload_bytes"] is not None

    def test_silent_when_source_type_absent(self):
        # Source-internal batchers leave source_type None; their output is measured when it reaches
        # the pipeline's own batcher, so this must not double-count.
        with mock.patch(_BATCHER_STATS) as recorded:
            batcher = Batcher(logger=mock.MagicMock())
            batcher.batch(pa.table({"a": [1, 2, 3]}))
            batcher.get_table()
        recorded.assert_not_called()
