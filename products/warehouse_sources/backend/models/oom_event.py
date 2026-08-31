from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models
from django.db.models import Count
from django.db.models.functions import Extract, Floor
from django.utils import timezone

from dateutil import parser

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, sane_repr

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

# Self-reported phases that rule a death out as a *merge* memory problem. Repartitioning only changes
# merge memory, so a death in any of these phases must not feed the repartition trigger, whatever
# killed the worker (an extract-phase OOM is real, but its remedy is chunking or routing, not a finer
# partition layout). An unknown phase (no report: rollout gap, expired key, Redis down) fails open,
# and so does "repartition": a rewrite death held partition-sized data of this schema, which is
# exactly the evidence the trigger runs on.
NON_MERGE_PHASES = ("extract", "load", "finished")


def evidence_freshness_bound_seconds() -> float:
    # A phase flip reaches Redis only on the next periodic sample, so evidence up to one interval old
    # is normal. Twice the interval tolerates one missed write; beyond that the report describes what
    # the run was doing earlier, not what killed it.
    return 2.0 * settings.DATA_WAREHOUSE_WORKLOAD_REPORT_INTERVAL_SECONDS


@dataclass(frozen=True, kw_only=True)
class BurstBucket:
    start_epoch: float
    schemas: int
    teams: int


class ExternalDataSchemaOOMEvent(TeamScopedRootMixin, UUIDModel):
    """Append-only log of *suspected* sync OOMs for an external data schema.

    Suspected, not confirmed, and the distinction is the point. What is actually detected is that the
    previous attempt stopped heartbeating, which is equally what a deploy, a pod eviction, a node
    drain, a native crash and a heartbeat lost by a healthy worker look like. Nothing in the signal
    itself distinguishes those from a real out-of-memory kill.

    Each row therefore snapshots the workload self-report evidence available at recording time (see
    `workload_report.py`): what phase the dead attempt was in, how big its own in-memory buffer was,
    and *aggregates only* about its pod co-tenants. Co-tenant identifiers are never stored — a pod is
    multi-tenant, so they belong to other teams, and this is a team-scoped row. Evidence is stored
    raw rather than as a baked verdict so the rules in `recent_count` stay tunable after the fact.

    A row is written once per Temporal retry attempt that follows a silent death, so this is an
    occurrence log rather than a counter.
    """

    # db_constraint=False on the Team FK: a real constraint takes a SHARE ROW EXCLUSIVE lock on the
    # hot posthog_team table on create. Team scoping is enforced at the app layer by TeamScopedRootMixin.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    schema = models.ForeignKey(
        "warehouse_sources.ExternalDataSchema", on_delete=models.CASCADE, related_name="oom_events"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Context captured from the prior attempt's last heartbeat.
    run_id = models.CharField(max_length=400, null=True, blank=True)
    host = models.CharField(max_length=400, null=True, blank=True)
    gap_seconds = models.FloatField(null=True, blank=True)
    # Workload self-report evidence, snapshotted at recording time because its Redis source expires.
    # Null means "no report available", which every rule treats as unknown, never as exonerating.
    # Column names deliberately differ from the telemetry event's property names where the semantics
    # differ, so joining rows to events during an incident can't silently mix the two: the event's
    # `self_report_age_seconds` is read-relative and its `co_tenant_max_peak_buffer_bytes` is the raw
    # max, while the row stores the death-relative age and the death-correlated max.
    self_phase = models.CharField(max_length=32, null=True, blank=True)
    self_report_age_at_death_seconds = models.FloatField(null=True, blank=True)
    self_peak_buffer_bytes = models.BigIntegerField(null=True, blank=True)
    # Aggregates only — never co-tenant schema/run ids (they belong to other teams).
    co_tenant_correlated_max_peak_buffer_bytes = models.BigIntegerField(null=True, blank=True)
    co_tenant_report_count = models.IntegerField(null=True, blank=True)

    all_teams = models.Manager()  # noqa: DJ012 — both are managers, ruff misclassifies this

    __repr__ = sane_repr("schema_id", "created_at")

    class Meta:
        # Django framework internals (cascade delete, related-object access, prefetch) read through
        # `_default_manager` / `_base_manager` and expect an unfiltered manager. Point them at the plain
        # `all_teams` so a schema delete that cascades to the log doesn't hit the fail-closed manager.
        # `objects` (from TeamScopedRootMixin) stays fail-closed for explicit app code.
        default_manager_name = "all_teams"
        indexes = [
            models.Index(fields=["schema", "created_at"], name="dwh_oom_schema_created_idx"),
            # The burst rule aggregates distinct schemas AND teams fleet-wide by time, which can't
            # ride the schema-scoped index above; both id columns ride along so the aggregate is an
            # index-only scan.
            models.Index(fields=["created_at", "schema", "team"], name="dwh_oom_created_idx"),
        ]

    @classmethod
    def recent_count(cls, schema: "ExternalDataSchema", *, days: int) -> int:
        """Occurrences within the last `days` that still look like this table's own merge OOM.

        Three rules narrow the raw stopped-heartbeating signal, all failing open so an occurrence the
        evidence cannot explain stays counted:

        * **Phase** — a death self-reported outside a merge is not a repartitioning problem, whatever
          killed the worker (see `NON_MERGE_PHASES`).
        * **Culprit** — a pod OOM kills every co-tenant, so a neighbour reporting a strictly larger
          peak buffer makes us plausibly collateral. Only peaks time-correlated with the death are
          carried (see `enrich_death_event_properties`), because a neighbour that crashed an hour
          earlier cannot exonerate this one.
        * **Infra burst** — a deploy, node drain or incident takes down many unrelated schemas at
          once. The burst must span many distinct teams as well as schemas, since one tenant's own
          outage is not infrastructure. Judged at read time because the window extends past the
          occurrence being judged, so later rows are part of its evidence.

        Phase and culprit additionally require the snapshot to be fresh relative to the death (see
        `_evidence_excludes`): self-reports are periodic, so stale evidence predates whatever killed
        the worker.

        Every retry attempt counts, including repeats within one job, because each is a fresh attempt
        at the same merge on whichever worker picks it up.

        The window is floored at `last_repartition_at`: a completed repartition addresses the OOMs
        that preceded it, so counting them again would re-trigger on a now-healthy table every
        cooldown until they age out. `blocks_coarsening` deliberately drops that floor.
        """
        since = timezone.now() - timedelta(days=days)
        last_repartition_at = schema.last_repartition_at
        if last_repartition_at:
            try:
                since = max(since, parser.parse(last_repartition_at))
            except (ValueError, TypeError):
                pass
        return cls._classified_count(cls._events_since(schema, since), since)

    @classmethod
    def _events_since(cls, schema: "ExternalDataSchema", since: datetime) -> list[dict[str, Any]]:
        return list(
            cls.objects.for_team(schema.team_id)
            .filter(schema_id=schema.pk, created_at__gte=since)
            .values(
                "created_at",
                "self_phase",
                "self_report_age_at_death_seconds",
                "self_peak_buffer_bytes",
                "co_tenant_correlated_max_peak_buffer_bytes",
            )
        )

    @classmethod
    def _classified_count(cls, events: list[dict[str, Any]], since: datetime) -> int:
        # Cheap rules first, so exonerated rows never reach the fleet-wide burst query below.
        candidates = [event for event in events if not cls._evidence_excludes(event)]
        if not candidates:
            return 0

        # One bucketed aggregate serves every candidate: distinct counts are monotone under
        # containment, so a half-window bucket that alone crosses the thresholds proves any window
        # containing it does too, and each candidate's verdict becomes an in-memory check. Bursts too
        # thin for a single bucket to prove fail open and count. Reaching one window back from `since`
        # keeps a burst straddling the boundary visible to the candidates near it.
        window = timedelta(seconds=settings.DATA_WAREHOUSE_OOM_INFRA_BURST_WINDOW_SECONDS)
        buckets = cls._burst_bucket_stats(since - window, timezone.now())
        return sum(1 for event in candidates if not cls._window_has_burst_bucket(event["created_at"], buckets))

    @classmethod
    def blocks_coarsening(cls, schema: "ExternalDataSchema", *, days: int) -> bool:
        """Whether recent evidence says a coarser layout would be unsafe for this table.

        Coarsening grows the merge working set, so it must not run on a table whose merges are already
        dying. The classification is deliberately reused rather than the raw log, because one
        fleet-wide restart would otherwise withhold coarsening from every table it touched. The rules
        fail open, so a death nothing explains still blocks.

        A merge-phase death whose own peak crossed `DATA_WAREHOUSE_COARSEN_BLOCK_MERGE_PEAK_BYTES`
        blocks as well, whatever verdict the rules reached, because the two directions are not
        symmetric: a merely plausible exclusion costs the split trigger a rewrite it did not need, but
        costs this one an enlarged merge on a table last seen holding real memory.
        """
        # No `last_repartition_at` floor, unlike `recent_count`. Coarsening undoes a split, so the
        # OOMs that justified that split are the evidence most worth keeping; flooring them away would
        # let the table coarsen straight back and split again on the next OOM.
        since = timezone.now() - timedelta(days=days)
        events = cls._events_since(schema, since)
        if cls._classified_count(events, since) > 0:
            return True
        peak_bound = settings.DATA_WAREHOUSE_COARSEN_BLOCK_MERGE_PEAK_BYTES
        return any(
            event["self_phase"] == "merge" and (event["self_peak_buffer_bytes"] or 0) > peak_bound for event in events
        )

    @classmethod
    def _evidence_excludes(cls, event: dict[str, Any]) -> bool:
        # Freshness gates every exoneration: a report flushed long before the death describes an
        # earlier phase of the run (a merge that OOMs within one report interval of leaving extract
        # still shows "extract" in Redis — the exact death this log exists to catch). Stale or
        # unknown-age evidence therefore cannot exclude; it fails open like missing evidence.
        age = event["self_report_age_at_death_seconds"]
        if age is None or age > evidence_freshness_bound_seconds():
            return False
        if event["self_phase"] in NON_MERGE_PHASES:
            return True
        own_peak = event["self_peak_buffer_bytes"]
        co_tenant_max = event["co_tenant_correlated_max_peak_buffer_bytes"]
        # Strictly larger, and only when both sides are known: a missing report on either side must
        # never exonerate, or a rollout gap would silently disable the trigger.
        return own_peak is not None and co_tenant_max is not None and co_tenant_max > own_peak

    @classmethod
    def _burst_bucket_stats(cls, start: datetime, end: datetime) -> list[BurstBucket]:
        """Distinct schema/team counts per half-window bucket over [start, end] — one query.

        Half the window so that any burst concentrated enough to matter (deploys and incidents land
        within minutes) fills at least one bucket that fits fully inside every candidate window
        around it. Deliberately cross-team (all_teams): the whole point is that a burst spans
        unrelated tenants; only counts leave the query, no team data crosses the boundary. Requiring
        distinct *teams* as well as schemas (see `_window_has_burst_bucket`) is what makes the
        verdict infrastructure — one tenant's own outage takes out many of its schemas at once and
        must not classify other tenants' contemporaneous deaths as infra.
        """
        bucket_seconds = settings.DATA_WAREHOUSE_OOM_INFRA_BURST_WINDOW_SECONDS / 2
        rows = (
            cls.all_teams.filter(created_at__gte=start, created_at__lte=end)
            .annotate(bucket=Floor(Extract("created_at", "epoch") / bucket_seconds))
            .values("bucket")
            .annotate(schemas=Count("schema_id", distinct=True), teams=Count("team_id", distinct=True))
        )
        return [
            BurstBucket(start_epoch=float(row["bucket"]) * bucket_seconds, schemas=row["schemas"], teams=row["teams"])
            for row in rows
        ]

    @staticmethod
    def _window_has_burst_bucket(created_at: datetime, buckets: list[BurstBucket]) -> bool:
        # Sound in the exclusion direction only: a bucket fully inside [t - window, t + window] whose
        # own distinct counts cross the thresholds proves the window's do (distinct counts are
        # monotone under containment). No such bucket proves nothing, so the candidate counts.
        window_seconds = float(settings.DATA_WAREHOUSE_OOM_INFRA_BURST_WINDOW_SECONDS)
        bucket_seconds = window_seconds / 2
        low = created_at.timestamp() - window_seconds
        high = created_at.timestamp() + window_seconds
        min_schemas = settings.DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS
        min_teams = settings.DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_TEAMS
        return any(
            bucket.start_epoch >= low
            and bucket.start_epoch + bucket_seconds <= high
            and bucket.schemas >= min_schemas
            and bucket.teams >= min_teams
            for bucket in buckets
        )
