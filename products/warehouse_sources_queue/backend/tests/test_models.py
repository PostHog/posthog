from products.warehouse_sources_queue.backend.models import SourceBatch, SourceBatchStatus


class TestSourceBatchModel:
    def test_sync_type_choices(self):
        assert SourceBatch.SyncType.FULL_REFRESH == "full_refresh"
        assert SourceBatch.SyncType.INCREMENTAL == "incremental"
        assert SourceBatch.SyncType.APPEND == "append"
        assert SourceBatch.SyncType.CDC == "cdc"

    def test_db_table(self):
        assert SourceBatch._meta.db_table == "sourcebatch"


class TestSourceBatchStatusModel:
    def test_state_choices(self):
        assert SourceBatchStatus.State.WAITING == "waiting"
        assert SourceBatchStatus.State.EXECUTING == "executing"
        assert SourceBatchStatus.State.SUCCEEDED == "succeeded"
        assert SourceBatchStatus.State.WAITING_RETRY == "waiting_retry"
        assert SourceBatchStatus.State.FAILED == "failed"

    def test_db_table(self):
        assert SourceBatchStatus._meta.db_table == "sourcebatchstatus"

    def test_batch_fk_has_no_db_constraint(self):
        field = SourceBatchStatus._meta.get_field("batch")
        assert field.db_constraint is False
