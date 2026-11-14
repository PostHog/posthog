from typing import Any

from django.db import models
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, sane_repr


class RepartitionStatus(models.TextChoices):
    FLAGGED = "flagged", "Flagged"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


TERMINAL_REPARTITION_STATUSES = frozenset(
    {RepartitionStatus.COMPLETED, RepartitionStatus.FAILED, RepartitionStatus.SKIPPED}
)


@frozen
class PartitionScheme:
    """One partition layout of a table, as the history row stores it."""

    mode: str | None
    format: str | None = None
    count: int | None = None
    size: int | None = None
    keys: tuple[str, ...] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "format": self.format,
            "count": self.count,
            "size": self.size,
            "keys": list(self.keys) if self.keys is not None else None,
        }

    def merged_into(self, stored: dict[str, Any] | None) -> dict[str, Any]:
        """The stored scheme with every value this one knows written over it.

        Steps of one repartition report the same scheme with different detail: the completed step
        knows the resolved mode but not the keys the flagged step recorded.
        """
        merged = dict(stored or {})
        merged.update({key: value for key, value in self.to_json().items() if value is not None})
        return merged


@frozen
class RepartitionTransition:
    """One step of one repartition, as `capture_repartition_event` reports it. A None value keeps the stored one."""

    team_id: int
    schema_id: str
    job_id: str | None
    status: RepartitionStatus
    trigger_reason: str | None = None
    requested_by_id: int | None = None
    scheme_before: PartitionScheme | None = None
    scheme_after: PartitionScheme | None = None
    max_partition_bytes_before: int | None = None
    rows_rewritten: int | None = None
    duration_seconds: float | None = None
    error_type: str | None = None


# Set on a running row when a newer attempt on the same schema starts, because the worker that ran it
# stopped without reporting an outcome.
INTERRUPTED_ERROR_TYPE = "interrupted"


class ExternalDataSchemaRepartition(TeamScopedRootMixin, UUIDModel):
    """Append-only history of the repartitions of one warehouse table.

    One row follows one repartition from the moment it is flagged to its outcome. The detector can flag a
    table in one sync and the rewrite runs in the next, so a step reported by a job with no row of its own
    adopts the open `flagged` row of the schema. A row that reached an outcome is never written again.
    """

    # db_constraint=False on the Team and User FKs: a real constraint takes a SHARE ROW EXCLUSIVE lock on
    # the hot parent table on create. Team scoping is enforced at the app layer by TeamScopedRootMixin.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    schema = models.ForeignKey(
        "warehouse_sources.ExternalDataSchema", on_delete=models.CASCADE, related_name="repartitions"
    )
    job_id = models.CharField(max_length=400, null=True, blank=True)
    trigger_reason = models.CharField(max_length=64, null=True, blank=True)
    requested_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    status = models.CharField(max_length=16, choices=RepartitionStatus.choices)
    # {"mode", "format", "count", "size", "keys"}
    scheme_before = models.JSONField(null=True, blank=True)
    scheme_after = models.JSONField(null=True, blank=True)
    max_partition_bytes_before = models.BigIntegerField(null=True, blank=True)
    rows_rewritten = models.BigIntegerField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    error_type = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    all_teams = models.Manager()  # noqa: DJ012 — both are managers, ruff misclassifies this

    __repr__ = sane_repr("schema_id", "status", "created_at")

    class Meta:
        # Same as `ExternalDataSchemaOOMEvent`: a schema delete cascades through `_default_manager`,
        # which must not be the fail-closed manager.
        default_manager_name = "all_teams"
        indexes = [
            models.Index(fields=["schema", "-created_at"], name="dwh_repart_schema_created_idx"),
        ]

    @classmethod
    def record_transition(cls, transition: RepartitionTransition) -> "ExternalDataSchemaRepartition":
        rows = cls.objects.for_team(transition.team_id).filter(schema_id=transition.schema_id)
        row: ExternalDataSchemaRepartition | None = None
        if transition.job_id is not None:
            row = rows.filter(job_id=transition.job_id, finished_at__isnull=True).order_by("-created_at").first()
        if row is None and transition.status != RepartitionStatus.FLAGGED:
            row = (
                rows.filter(status=RepartitionStatus.FLAGGED, finished_at__isnull=True).order_by("-created_at").first()
            )

        if transition.status == RepartitionStatus.RUNNING:
            # Only one attempt runs at a time, so an older running row lost its worker.
            stale = rows.filter(status=RepartitionStatus.RUNNING, finished_at__isnull=True)
            if row is not None:
                stale = stale.exclude(pk=row.pk)
            stale.update(status=RepartitionStatus.FAILED, error_type=INTERRUPTED_ERROR_TYPE, finished_at=timezone.now())

        if row is None:
            row = cls(team_id=transition.team_id, schema_id=transition.schema_id)
        row._apply(transition)
        row.save()
        return row

    def _apply(self, transition: RepartitionTransition) -> None:
        self.status = transition.status
        if transition.job_id is not None:
            self.job_id = transition.job_id
        if transition.trigger_reason is not None:
            self.trigger_reason = transition.trigger_reason
        if transition.requested_by_id is not None:
            self.requested_by_id = transition.requested_by_id
        if transition.scheme_before is not None:
            self.scheme_before = transition.scheme_before.merged_into(self.scheme_before)
        if transition.scheme_after is not None:
            self.scheme_after = transition.scheme_after.merged_into(self.scheme_after)
        if transition.max_partition_bytes_before is not None:
            self.max_partition_bytes_before = transition.max_partition_bytes_before
        if transition.rows_rewritten is not None:
            self.rows_rewritten = transition.rows_rewritten
        if transition.duration_seconds is not None:
            self.duration_seconds = transition.duration_seconds
        if transition.error_type is not None:
            self.error_type = transition.error_type[:200]
        if transition.status in TERMINAL_REPARTITION_STATUSES:
            self.finished_at = timezone.now()
