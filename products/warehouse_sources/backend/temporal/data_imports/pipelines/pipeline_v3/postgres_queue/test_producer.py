import json
from typing import Any

import pytest
from unittest.mock import MagicMock, PropertyMock, patch

import psycopg

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    PostgresProducer,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult


def _default_kwargs(**kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "database_url": "postgres://unused:unused@localhost/unused",
        "team_id": 1,
        "job_id": "job-1",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "resource_name": "test_resource",
        "sync_type": "full_refresh",
        "run_uuid": "run-1",
        "logger": MagicMock(),
    }
    defaults.update(kwargs)
    return defaults


def _make_producer(**kwargs: Any) -> PostgresProducer:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.psycopg"
    ) as mock_psycopg:
        mock_conn = MagicMock()
        mock_psycopg.Connection.connect.return_value = mock_conn
        producer = PostgresProducer(**_default_kwargs(**kwargs))
    return producer


def _make_batch_result(batch_index: int = 0) -> BatchWriteResult:
    return BatchWriteResult(
        batch_index=batch_index,
        s3_path="s3://bucket/path",
        row_count=100,
        byte_size=1024,
        timestamp_ns=123456789,
    )


def _mock_conn(producer: PostgresProducer) -> Any:
    return producer._conn


class TestPostgresProducerConnectRetry:
    _CONNECT_TARGET = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.psycopg.Connection.connect"
    _SLEEP_TARGET = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.time.sleep"

    def test_recovers_from_transient_connection_drop(self) -> None:
        mock_conn = MagicMock()
        with (
            patch(
                self._CONNECT_TARGET,
                side_effect=[psycopg.OperationalError("server closed the connection unexpectedly"), mock_conn],
            ),
            patch(self._SLEEP_TARGET) as mock_sleep,
        ):
            producer = PostgresProducer(**_default_kwargs())

        assert producer._conn is mock_conn
        mock_sleep.assert_called_once()

    def test_raises_once_retries_are_exhausted(self) -> None:
        with (
            patch(
                self._CONNECT_TARGET,
                side_effect=psycopg.OperationalError("server closed the connection unexpectedly"),
            ) as mock_connect,
            patch(self._SLEEP_TARGET),
        ):
            with pytest.raises(psycopg.OperationalError):
                PostgresProducer(**_default_kwargs())

        assert mock_connect.call_count == 3


class TestPostgresProducerSendBatch:
    def test_inserts_row_on_send(self) -> None:
        producer = _make_producer()
        batch_result = _make_batch_result(batch_index=1)

        producer.send_batch_notification(batch_result)

        mock = _mock_conn(producer)
        mock.execute.assert_called_once()
        sql = mock.execute.call_args[0][0]
        params = mock.execute.call_args[0][1]
        assert "INSERT INTO" in sql
        assert params["team_id"] == 1
        assert params["s3_path"] == "s3://bucket/path"
        assert params["row_count"] == 100
        assert params["batch_index"] == 1

    def test_metadata_includes_optional_fields(self) -> None:
        producer = _make_producer(
            primary_keys=["id"],
            partition_count=4,
            cdc_write_mode="upsert",
            cdc_table_mode="merge",
        )
        batch_result = _make_batch_result(batch_index=1)

        producer.send_batch_notification(batch_result)

        mock = _mock_conn(producer)
        params = mock.execute.call_args[0][1]
        metadata = json.loads(params["metadata"])
        assert metadata["primary_keys"] == ["id"]
        assert metadata["partition_count"] == 4
        assert metadata["cdc_write_mode"] == "upsert"
        assert metadata["cdc_table_mode"] == "merge"
        assert metadata["timestamp_ns"] == 123456789


class TestPostgresProducerFlush:
    def test_returns_count_and_resets(self) -> None:
        producer = _make_producer()
        producer.send_batch_notification(_make_batch_result(batch_index=1))
        producer.send_batch_notification(_make_batch_result(batch_index=2))
        producer.send_batch_notification(_make_batch_result(batch_index=3))

        count = producer.flush()

        assert count == 3

        count = producer.flush()
        assert count == 0

    def test_flush_with_no_batches(self) -> None:
        producer = _make_producer()

        assert producer.flush() == 0


class TestPostgresProducerClose:
    def test_closes_connection(self) -> None:
        producer = _make_producer()
        mock = _mock_conn(producer)
        type(mock).closed = PropertyMock(return_value=False)

        producer.close()

        mock.close.assert_called_once()

    def test_close_idempotent(self) -> None:
        producer = _make_producer()
        mock = _mock_conn(producer)
        type(mock).closed = PropertyMock(return_value=True)

        producer.close()

        mock.close.assert_not_called()


class TestPostgresProducerSupersede:
    def test_supersedes_old_runs_on_batch_zero(self) -> None:
        producer = _make_producer(is_resume=False)
        batch_result = _make_batch_result(batch_index=0)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.BatchQueue.supersede_other_runs",
            return_value=2,
        ) as mock_supersede:
            producer.send_batch_notification(batch_result)

        mock_supersede.assert_called_once_with(
            producer._conn,
            job_id="job-1",
            current_run_uuid="run-1",
            spare_runs_with_progress=False,
        )

    @pytest.mark.parametrize(
        "sync_type,spare",
        [("full_refresh", False), ("incremental", True), ("append", True), ("cdc", True)],
    )
    def test_only_full_refresh_supersedes_a_run_that_is_still_loading(self, sync_type: str, spare: bool) -> None:
        """A fresh full_refresh overwrites the table on batch 0, so an older attempt's loaded rows
        are discarded either way and its queued batches are dead weight on the serial per-schema
        gate. Every other sync type keeps the sparing rule, because partially merged work survives."""
        producer = _make_producer(is_resume=False, sync_type=sync_type)
        batch_result = _make_batch_result(batch_index=0)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.BatchQueue.supersede_other_runs",
            return_value=0,
        ) as mock_supersede:
            producer.send_batch_notification(batch_result)

        assert mock_supersede.call_args.kwargs["spare_runs_with_progress"] is spare

    def test_does_not_supersede_on_non_zero_batch(self) -> None:
        producer = _make_producer(is_resume=False)
        batch_result = _make_batch_result(batch_index=1)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.BatchQueue.supersede_other_runs",
        ) as mock_supersede:
            producer.send_batch_notification(batch_result)

        mock_supersede.assert_not_called()

    def test_does_not_supersede_on_resume(self) -> None:
        producer = _make_producer(is_resume=True)
        batch_result = _make_batch_result(batch_index=0)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.BatchQueue.supersede_other_runs",
        ) as mock_supersede:
            producer.send_batch_notification(batch_result)

        mock_supersede.assert_not_called()


class TestPostgresProducerProperties:
    def test_sync_type_property(self) -> None:
        producer = _make_producer(sync_type="incremental")

        assert producer.sync_type == "incremental"

    def test_is_first_ever_sync_property(self) -> None:
        producer = _make_producer(is_first_ever_sync=True)

        assert producer.is_first_ever_sync is True

        producer.is_first_ever_sync = False
        assert producer.is_first_ever_sync is False


def _inserted_rows(producer: PostgresProducer) -> list[tuple[int, bool]]:
    return [
        (call.args[1]["batch_index"], call.args[1]["is_final_batch"])
        for call in _mock_conn(producer).execute.call_args_list
        if "INSERT INTO" in call.args[0]
    ]


class TestPostgresProducerHeldBatch:
    # A run whose last data row is not its own final marker makes the loader read that parquet
    # file twice: once to write it, once to finish the run.

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.BatchQueue.supersede_other_runs",
        return_value=0,
    )
    def test_the_last_data_row_carries_the_final_flag(self, _supersede: MagicMock) -> None:
        producer = _make_producer()
        batches = [_make_batch_result(batch_index=i) for i in range(3)]

        for index, batch in enumerate(batches):
            producer.hold_batch(batch, cumulative_row_count=100 * (index + 1), incremental_last_value=10 * index)
            assert _inserted_rows(producer) == [(i, False) for i in range(index)]
        producer.send_final_batch(batches[-1], total_batches=3, total_rows=300, data_folder="s3://d", schema_path=None)

        assert _inserted_rows(producer) == [(0, False), (1, False), (2, True)]
        assert [
            json.loads(call.args[1]["metadata"])["incremental_last_value"]
            for call in _mock_conn(producer).execute.call_args_list
        ] == [0, 10, 20]
        final_params = _mock_conn(producer).execute.call_args_list[-1].args[1]
        assert (final_params["total_batches"], final_params["total_rows"], final_params["cumulative_row_count"]) == (
            3,
            300,
            300,
        )

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.BatchQueue.supersede_other_runs",
        return_value=0,
    )
    def test_a_single_batch_run_inserts_exactly_one_row(self, _supersede: MagicMock) -> None:
        producer = _make_producer()
        batch = _make_batch_result(batch_index=0)

        producer.hold_batch(batch, cumulative_row_count=100)
        producer.send_final_batch(batch, total_batches=1, total_rows=100, data_folder="s3://d", schema_path="s3://s")

        assert _inserted_rows(producer) == [(0, True)]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.BatchQueue.supersede_other_runs",
        return_value=0,
    )
    def test_a_released_row_leaves_the_final_marker_as_a_second_row(self, _supersede: MagicMock) -> None:
        # A resumable source releases the held row before it commits a cursor. The run still needs a
        # final marker, and the loader still accepts the last batch repeated with the flag set.
        producer = _make_producer()
        batch = _make_batch_result(batch_index=0)

        producer.hold_batch(batch, cumulative_row_count=100)
        assert producer.release_held_batch() is True
        assert producer.release_held_batch() is False
        producer.send_final_batch(batch, total_batches=1, total_rows=100, data_folder="s3://d", schema_path=None)

        assert _inserted_rows(producer) == [(0, False), (0, True)]

    def test_superseding_fires_when_batch_zero_is_staged_not_when_it_is_inserted(self) -> None:
        # Holding the row back must not delay retiring the previous attempt's stalled batches, or
        # they stay claimable for one extra batch of extraction time.
        producer = _make_producer(is_resume=False)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer.BatchQueue.supersede_other_runs",
            return_value=0,
        ) as mock_supersede:
            producer.hold_batch(_make_batch_result(batch_index=0), cumulative_row_count=100)

        mock_supersede.assert_called_once_with(
            producer._conn, job_id="job-1", current_run_uuid="run-1", spare_runs_with_progress=False
        )
        assert _inserted_rows(producer) == []
