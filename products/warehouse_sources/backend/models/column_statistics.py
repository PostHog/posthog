from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr


class WarehouseColumnStatistics(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Per-column data profile for a synced warehouse table, surfaced to the AI agent.

    One row per (table, column). Stats are derived from the Delta transaction log's per-file statistics
    (`num_records`, `null_count`, `min`, `max`) — aggregated across the snapshot's live files, so they
    reflect the whole current table without scanning any data and are correct for full-refresh, append and
    incremental-upsert syncs alike. Unlike [[WarehouseColumnAnnotation]] these are wholly system-owned and
    overwritten on every recompute (never user-edited), so there is no table-level row — `row_count` and
    `computed_at` are denormalised onto every column row.

    `min`/`max` are stored as strings because a column can be int, datetime, decimal, etc.; `column_type`
    records what they were computed against. delta-rs may omit log stats for some types (`has_min_max`
    is then False) and truncates long-string min/max, so treat string bounds as approximate.
    """

    # db_constraint=False on the FKs to hot tables (posthog_team, posthog_user): creating a real FK
    # constraint takes a SHARE ROW EXCLUSIVE lock on the parent, which stalls under write traffic. Team
    # scoping is enforced at the app level by TeamScopedRootMixin, and these are derived rows, so we don't
    # need DB-level referential integrity here. The table FK targets a non-hot table, so it keeps its constraint.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    table = models.ForeignKey(
        "warehouse_sources.DataWarehouseTable", on_delete=models.CASCADE, related_name="column_statistics"
    )
    column_name = models.TextField()
    column_type = models.TextField(blank=True, default="")

    # Denormalised onto every column row — one recompute writes them all atomically.
    row_count = models.BigIntegerField(null=True)
    null_count = models.BigIntegerField(null=True)
    null_fraction = models.FloatField(null=True)
    min_value = models.TextField(null=True, blank=True)
    max_value = models.TextField(null=True, blank=True)
    # False when the Delta log carried no min/max for this column (e.g. nested/binary types).
    has_min_max = models.BooleanField(default=False)

    computed_at = models.DateTimeField(null=True)
    # Delta table version the stats were computed against; provenance + lets us spot staleness.
    computed_for_delta_version = models.BigIntegerField(null=True)
    # How the stats were produced. "delta_log" today; reserved for a future scan/sample basis.
    stats_basis = models.CharField(max_length=32, default="delta_log")

    __repr__ = sane_repr("table_id", "column_name", "computed_at")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["table", "column_name"], name="unique_table_column_statistics"),
        ]
