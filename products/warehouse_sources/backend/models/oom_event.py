from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, sane_repr

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


class ExternalDataSchemaOOMEvent(TeamScopedRootMixin, UUIDModel):
    """Append-only log of detected sync OOMs (pod heartbeat-timeouts) for an external data schema.

    Recorded once per Temporal retry attempt that follows an OOM'd attempt — a single job can OOM
    many times before its terminal status — so this is an occurrence log, not a counter. Drives the
    repartition trigger via `recent_count()`; kept bounded by pruning to a retention window.
    """

    # db_constraint=False on the Team FK: a real constraint takes a SHARE ROW EXCLUSIVE lock on the
    # hot posthog_team table on create. Team scoping is enforced at the app layer by TeamScopedRootMixin.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    schema = models.ForeignKey(
        "warehouse_sources.ExternalDataSchema", on_delete=models.CASCADE, related_name="oom_events"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Context captured from the prior (OOM'd) attempt's last heartbeat.
    run_id = models.CharField(max_length=400, null=True, blank=True)
    host = models.CharField(max_length=400, null=True, blank=True)
    gap_seconds = models.FloatField(null=True, blank=True)

    all_teams = models.Manager()  # noqa: DJ012 — both are managers, ruff misclassifies this

    __repr__ = sane_repr("schema_id", "created_at")

    class Meta:
        # Django framework internals (cascade delete, related-object access, prefetch) read through
        # `_default_manager` / `_base_manager` and expect an unfiltered manager. Point them at the plain
        # `all_teams` so a schema delete that cascades to `oom_events` doesn't hit the fail-closed manager.
        # `objects` (from TeamScopedRootMixin) stays fail-closed for explicit app code (recent_count / recording).
        default_manager_name = "all_teams"
        indexes = [
            models.Index(fields=["schema", "created_at"], name="dwh_oom_schema_created_idx"),
        ]

    @classmethod
    def recent_count(cls, schema: "ExternalDataSchema", *, days: int = 7) -> int:
        """Number of OOM occurrences recorded for this schema within the last `days`."""
        since = timezone.now() - timedelta(days=days)
        return cls.objects.for_team(schema.team_id).filter(schema_id=schema.pk, created_at__gte=since).count()
