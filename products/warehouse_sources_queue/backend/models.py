from django.db import models

from posthog.models.utils import UUIDModel, sane_repr


class SourceBatch(UUIDModel):
    class SyncType(models.TextChoices):
        FULL_REFRESH = "full_refresh", "full_refresh"
        INCREMENTAL = "incremental", "incremental"
        APPEND = "append", "append"
        CDC = "cdc", "cdc"

    class LatestState(models.TextChoices):
        # 'pending' means "no status row yet" — deliberately distinct from
        # SourceBatchStatus.State.WAITING, which claim semantics treat differently.
        PENDING = "pending", "pending"
        WAITING = "waiting", "waiting"
        EXECUTING = "executing", "executing"
        SUCCEEDED = "succeeded", "succeeded"
        WAITING_RETRY = "waiting_retry", "waiting_retry"
        FAILED = "failed", "failed"

    team_id = models.BigIntegerField()
    schema_id = models.CharField(max_length=200)
    source_id = models.CharField(max_length=200)
    job_id = models.CharField(max_length=200, help_text="FK to ExternalDataJob (UUID as string).")
    run_uuid = models.CharField(max_length=200)

    batch_index = models.IntegerField()
    s3_path = models.TextField()
    row_count = models.IntegerField()
    byte_size = models.BigIntegerField()
    is_final_batch = models.BooleanField()
    total_batches = models.IntegerField(null=True, blank=True)
    total_rows = models.BigIntegerField(null=True, blank=True)
    sync_type = models.CharField(max_length=32, choices=SyncType.choices)
    cumulative_row_count = models.BigIntegerField(default=0)

    resource_name = models.CharField(max_length=400)
    is_resume = models.BooleanField(default=False)
    is_first_ever_sync = models.BooleanField(default=False)

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Stores partitioning config, CDC mode, primary keys, schema path, data folder, etc.",
    )

    # Denormalized mirror of the latest sourcebatchstatus row, maintained by the
    # dual-write CTEs in jobs_db so hot readers don't re-derive state from the
    # append-only log. sourcebatchstatus remains the source of truth.
    latest_state = models.CharField(
        max_length=32, choices=LatestState.choices, default=LatestState.PENDING, db_default="pending"
    )
    latest_attempt = models.SmallIntegerField(default=0, db_default=0)
    # NULL means "never dual-written" — the backfill command's target marker.
    state_changed_at = models.DateTimeField(null=True, blank=True)
    # Denormalized from the failed status row's error payload ({"superseded": true},
    # written only by supersede_other_runs). Lets the reconcile sweep judge
    # candidacy from this table alone instead of a per-batch status lateral,
    # whose cost melted down under failure storms.
    superseded = models.BooleanField(default=False, db_default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("id", "team_id", "schema_id", "batch_index")

    class Meta:
        db_table = "sourcebatch"
        indexes = [
            models.Index(fields=["team_id", "schema_id"], name="sb_team_schema_idx"),
            models.Index(fields=["run_uuid"], name="sb_run_uuid_idx"),
            models.Index(fields=["run_uuid", "batch_index"], name="sb_run_uuid_bi_idx"),
            # Serves the job-scoped scans (supersede_other_runs on every fresh run's
            # first batch, lock-takeover activity summary, orphan reconcile counts),
            # which otherwise seq-scan every retained partition per call.
            models.Index(fields=["job_id"], name="sb_job_id_idx"),
            models.Index(
                fields=["team_id", "created_at", "batch_index"],
                name="sb_claimable_idx",
                condition=models.Q(latest_state__in=["pending", "waiting_retry"]),
            ),
            models.Index(
                fields=["run_uuid", "latest_state", "batch_index"],
                name="sb_run_gate_idx",
                condition=models.Q(latest_state__in=["executing", "waiting_retry", "failed"]),
            ),
            models.Index(
                fields=["team_id", "schema_id"],
                name="sb_schema_busy_idx",
                condition=models.Q(latest_state="executing"),
            ),
            models.Index(
                fields=["state_changed_at"],
                name="sb_failed_changed_idx",
                condition=models.Q(latest_state="failed"),
            ),
        ]


class SourceBatchStatus(UUIDModel):
    class State(models.TextChoices):
        WAITING = "waiting", "waiting"
        EXECUTING = "executing", "executing"
        SUCCEEDED = "succeeded", "succeeded"
        WAITING_RETRY = "waiting_retry", "waiting_retry"
        FAILED = "failed", "failed"

    # No DB-level FK constraint: sourcebatch is range-partitioned on
    # created_at, making its PK composite (id, created_at). A real FK
    # would require batch_created_at here. Referential integrity is
    # enforced in application code — statuses are only inserted for
    # known batch IDs.
    batch = models.ForeignKey(
        SourceBatch,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="statuses",
    )
    job_state = models.CharField(max_length=32, choices=State.choices)
    attempt = models.SmallIntegerField(default=0)
    exec_time = models.DateTimeField(null=True, blank=True)
    error_response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sourcebatchstatus"
        indexes = [
            models.Index(
                fields=["batch_id", "-created_at", "-id", "job_state"],
                name="sbs_batch_id_desc_state_idx",
            ),
        ]


class SourceGroupLease(models.Model):
    """Lease-based mutual exclusion for processing a (team_id, schema_id) group.

    Replaces the session-scoped Postgres advisory lock that previously gated
    group claiming. A lease row is claimed via a conditional upsert and renewed
    by the consumer heartbeat; an abandoned lease (pod SIGKILLed, pgbouncer
    session lingering, node lost) simply expires, so any surviving pod can
    reclaim the group once ``expires_at`` passes. All access is via raw SQL in
    ``postgres_queue/jobs_db.py`` — this model exists for migration/introspection.
    """

    team_id = models.BigIntegerField()
    schema_id = models.CharField(max_length=200)
    owner_token = models.CharField(max_length=64, help_text="Per-pod identity (uuid4) of the current lease holder.")
    expires_at = models.DateTimeField()
    acquired_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    __repr__ = sane_repr("team_id", "schema_id", "owner_token", "expires_at")

    class Meta:
        db_table = "sourcegrouplease"
        constraints = [
            models.UniqueConstraint(fields=["team_id", "schema_id"], name="sgl_team_schema_uniq"),
        ]
        indexes = [
            models.Index(fields=["expires_at"], name="sgl_expires_at_idx"),
        ]
