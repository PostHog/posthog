from django.db.models import UniqueConstraint

from products.warehouse_sources_queue.backend.models import (
    SourceBatch,
    SourceBatchDuckgresApply,
    SourceBatchDuckgresStatus,
    SourceBatchStatus,
)


class TestSourceBatchModel:
    def test_sync_type_choices(self):
        values = {c.value for c in SourceBatch.SyncType}
        assert values == {"full_refresh", "incremental", "append", "cdc"}

    def test_db_table(self):
        assert SourceBatch._meta.db_table == "sourcebatch"


class TestSourceBatchStatusModel:
    def test_state_choices(self):
        values = {c.value for c in SourceBatchStatus.State}
        assert values == {"waiting", "executing", "succeeded", "waiting_retry", "failed"}

    def test_db_table(self):
        assert SourceBatchStatus._meta.db_table == "sourcebatchstatus"

    def test_batch_fk_has_no_db_constraint(self):
        field = SourceBatchStatus._meta.get_field("batch")
        assert not field.db_constraint  # type: ignore[attr-defined]


class TestSourceBatchDuckgresStatusModel:
    def test_state_choices(self):
        values = {c.value for c in SourceBatchDuckgresStatus.State}
        assert values == {"executing", "succeeded", "waiting_retry", "failed"}

    def test_db_table(self):
        assert SourceBatchDuckgresStatus._meta.db_table == "sourcebatchduckgresstatus"

    def test_batch_fk_has_no_db_constraint(self):
        field = SourceBatchDuckgresStatus._meta.get_field("batch")
        assert not field.db_constraint  # type: ignore[attr-defined]


class TestSourceBatchDuckgresApplyModel:
    def test_db_table(self):
        assert SourceBatchDuckgresApply._meta.db_table == "sourcebatchduckgresapply"

    def test_batch_fk_has_no_db_constraint(self):
        field = SourceBatchDuckgresApply._meta.get_field("batch")
        assert not field.db_constraint  # type: ignore[attr-defined]

    def test_unique_constraint_matches_apply_key(self):
        constraint = next(
            constraint
            for constraint in SourceBatchDuckgresApply._meta.constraints
            if constraint.name == "sbdga_unique_batch_apply"
        )

        assert isinstance(constraint, UniqueConstraint)
        assert tuple(constraint.fields) == ("team_id", "schema_id", "run_uuid", "batch_index")
