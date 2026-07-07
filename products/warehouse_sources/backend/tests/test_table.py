import subprocess

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.models.table import ChdbQueryTimeout, DataWarehouseTable, run_chdb_query


class TestRunChdbQuery:
    def test_hung_query_is_killed_and_raises_instead_of_blocking(self) -> None:
        # Real subprocess: chdb import alone exceeds the timeout, so this exercises the
        # actual kill path. Guards the regression where a stalled chdb S3 read wedged web
        # workers indefinitely (no timeout around the embedded query).
        with pytest.raises(ChdbQueryTimeout, match="timed out"):
            run_chdb_query("SELECT sleep(2)", timeout=0.5)

    def test_timeout_is_a_suppressed_error_so_the_cluster_fallback_is_not_noise(self) -> None:
        # The timeout has a working cluster fallback, so it must not be surfaced to error
        # tracking. Guards the regression where the intended timeout-and-fallback path
        # showed up as an unhandled-looking exception.
        timed_out = subprocess.TimeoutExpired(cmd=[], timeout=0.5)
        with patch("products.warehouse_sources.backend.models.table.subprocess.run", side_effect=timed_out):
            with pytest.raises(ChdbQueryTimeout) as exc_info:
                run_chdb_query("SELECT count() FROM s3('https://example.com/table/')")

        assert DataWarehouseTable()._is_suppressed_chdb_error(exc_info.value)

    def test_suppressed_delta_error_classification_survives_subprocess_boundary(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Code: 36. DB::Exception: Unsupported DeltaLake type: timestamp_ntz. (BAD_ARGUMENTS)",
        )
        with patch("products.warehouse_sources.backend.models.table.subprocess.run", return_value=completed):
            with pytest.raises(RuntimeError) as exc_info:
                run_chdb_query("DESCRIBE TABLE s3('https://example.com/table/')")

        assert DataWarehouseTable()._is_suppressed_chdb_error(exc_info.value)
