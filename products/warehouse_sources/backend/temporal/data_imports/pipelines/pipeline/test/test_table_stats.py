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

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.table_stats"
_STATS = f"{_MODULE}.record_table_stats"
_CAPTURE = f"{_MODULE}.posthoganalytics.capture"
_POD = f"{_MODULE}._pod_name"
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

    def test_outlier_logs_and_captures_event_with_full_tags(self):
        logger = mock.MagicMock()
        with mock.patch(_CAPTURE) as capture, mock.patch(_POD, return_value="warehouse-sources-load-abc123"):
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

        capture.assert_called_once()
        assert capture.call_args.kwargs["event"] == "data_import_large_table"
        assert capture.call_args.kwargs["distinct_id"]  # machine id used as distinct_id
        props = capture.call_args.kwargs["properties"]
        assert props["source_type"] == "Stripe"
        assert props["stage"] == "batcher"
        assert props["team_id"] == 7
        assert props["schema_name"] == "charges"
        assert props["num_rows"] == 10
        assert props["payload_bytes"] == OUTLIER_TABLE_BYTES
        assert props["pod_name"] == "warehouse-sources-load-abc123"

    def test_capture_failure_is_swallowed(self):
        # A telemetry failure must never fail the import.
        with mock.patch(_CAPTURE, side_effect=RuntimeError("boom")):
            record_table_stats(
                source_type="Stripe",
                stage="batcher",
                num_rows=10,
                payload_bytes=OUTLIER_TABLE_BYTES,
                logger=mock.MagicMock(),
            )

    @parameterized.expand([("below_threshold", OUTLIER_TABLE_BYTES - 1), ("bytes_unknown", None)])
    def test_no_outlier_log_or_event(self, _name, payload_bytes):
        logger = mock.MagicMock()
        with mock.patch(_CAPTURE) as capture:
            record_table_stats(
                source_type="Stripe", stage="pipeline", num_rows=10, payload_bytes=payload_bytes, logger=logger
            )
        logger.warning.assert_not_called()
        capture.assert_not_called()


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
