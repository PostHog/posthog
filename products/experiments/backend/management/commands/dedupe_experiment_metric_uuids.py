"""Dedupe metric UUIDs across an experiment's metrics / metrics_secondary / saved metrics.

Some experiments accumulated duplicate metric UUIDs (likely via MCP/LLM update
flows that copied a metric without regenerating its UUID). The service layer
now rewrites duplicates on every write, but pre-existing rows in the DB still
carry the corruption. This command performs a one-shot backfill that mirrors
what ``_assign_uuids_to_metrics`` does on the live path: the first occurrence
of a duplicated UUID keeps it (so any attached ``ExperimentMetricResult`` rows
or saved-metric links stay valid), and later occurrences get fresh UUIDs that
are appended to the corresponding ordering array.

Run with ``--dry-run`` first to confirm the affected count before writing.
"""

from copy import deepcopy
from uuid import uuid4

from django.core.management.base import BaseCommand
from django.db import connection, transaction

import structlog

from products.experiments.backend.models.experiment import Experiment, ExperimentToSavedMetric

logger = structlog.get_logger(__name__)


# Returns experiment ids that have at least one duplicated metric uuid across
# the union of inline `metrics`, inline `metrics_secondary`, and attached
# saved-metric query uuids.
_AFFECTED_IDS_SQL = """
WITH metrics_unnested AS (
    SELECT e.id AS experiment_id, elem->>'uuid' AS metric_uuid
    FROM posthog_experiment e
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(e.metrics, '[]'::jsonb)) AS elem
    WHERE e.deleted IS NOT TRUE AND elem->>'uuid' IS NOT NULL

    UNION ALL

    SELECT e.id, elem->>'uuid'
    FROM posthog_experiment e
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(e.metrics_secondary, '[]'::jsonb)) AS elem
    WHERE e.deleted IS NOT TRUE AND elem->>'uuid' IS NOT NULL

    UNION ALL

    SELECT e.id, sm.query->>'uuid'
    FROM posthog_experiment e
    JOIN posthog_experimenttosavedmetric link ON link.experiment_id = e.id
    JOIN posthog_experimentsavedmetric sm ON sm.id = link.saved_metric_id
    WHERE e.deleted IS NOT TRUE AND sm.query->>'uuid' IS NOT NULL
)
SELECT experiment_id
FROM metrics_unnested
GROUP BY experiment_id, metric_uuid
HAVING COUNT(*) > 1
"""


def _dedupe_metrics(metrics: list[dict] | None, seen: set[str]) -> tuple[list[dict] | None, bool]:
    """Walk ``metrics`` in order. First occurrence of a uuid keeps it; later
    occurrences (and missing uuids) get fresh ones. Returns the prepared list
    plus a `changed` flag.

    Preserves ``None`` (mirrors ``_assign_uuids_to_metrics`` on the live path) so
    the backfill never normalizes a genuinely-null column into an empty list.
    """
    if not metrics:
        return metrics, False
    prepared = deepcopy(metrics)
    changed = False
    for metric in prepared:
        original = metric.get("uuid")
        if not original or original in seen:
            new_uuid = str(uuid4())
            metric["uuid"] = new_uuid
            seen.add(new_uuid)
            changed = True
        else:
            seen.add(original)
    return prepared, changed


def _reconcile_ordering(
    ordering: list[str] | None,
    original_uuids: set[str],
    new_uuids: set[str],
    protected_uuids: set[str],
) -> list[str] | None:
    """Reconcile an ordering array with a dedup that rewrote inline metric uuids.

    A duplicated uuid's first occurrence keeps its value (so its ordering entry
    stays valid); each later occurrence is regenerated into a brand-new uuid that
    has to be appended. When the regenerated value displaced the *only* inline
    use of the old uuid, the old uuid is now an orphan in the ordering and is
    dropped — e.g. a metric duplicated across the primary and secondary lists
    leaves the secondary's pre-dedup uuid pointing at nothing.

    ``protected_uuids`` are never removed: a saved-metric uuid can sit in the
    ordering while also matching an inline metric's original uuid (the inline
    copy is the one that gets regenerated), and that saved-metric reference must
    survive. Removal is therefore scoped to orphaned *inline* uuids only.
    """
    added = new_uuids - original_uuids
    removed = (original_uuids - new_uuids) - protected_uuids
    if not added and not removed:
        return ordering
    current = [uuid for uuid in (ordering or []) if uuid not in removed]
    for uuid in added:
        if uuid not in current:
            current.append(uuid)
    return current


class Command(BaseCommand):
    help = "Dedupe experiment metric UUIDs across metrics / metrics_secondary / saved metrics."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]

        with connection.cursor() as cursor:
            cursor.execute(_AFFECTED_IDS_SQL)
            affected_ids = sorted({row[0] for row in cursor.fetchall()})

        if not affected_ids:
            self.stdout.write("No experiments to dedupe.")
            return

        self.stdout.write(f"{'[DRY RUN] ' if dry_run else ''}Found {len(affected_ids)} experiments needing dedup.")

        updated = 0
        failed = 0
        skipped = 0

        # The affected set is small (a few hundred rows), so a single pass with no
        # chunking keeps the command simple.
        saved_uuids_by_experiment: dict[int, set[str]] = {}
        for link in (
            ExperimentToSavedMetric.objects.filter(experiment_id__in=affected_ids)
            .select_related("saved_metric")
            .only("experiment_id", "saved_metric__query")
        ):
            sm = link.saved_metric
            if sm and sm.query:
                uuid = sm.query.get("uuid")
                if uuid:
                    saved_uuids_by_experiment.setdefault(link.experiment_id, set()).add(uuid)

        qs = Experiment.objects.filter(id__in=affected_ids).only(
            "id",
            "metrics",
            "metrics_secondary",
            "primary_metrics_ordered_uuids",
            "secondary_metrics_ordered_uuids",
        )
        for experiment in qs.iterator():
            try:
                # Saved-metric uuids are fixed points: they seed dedup's
                # uniqueness space and are never removed from the orderings.
                saved_metric_uuids: set[str] = set(saved_uuids_by_experiment.get(experiment.id, set()))
                seen: set[str] = set(saved_metric_uuids)

                original_primary_uuids: set[str] = {uuid for m in (experiment.metrics or []) if (uuid := m.get("uuid"))}
                original_secondary_uuids: set[str] = {
                    uuid for m in (experiment.metrics_secondary or []) if (uuid := m.get("uuid"))
                }

                new_primary, primary_changed = _dedupe_metrics(experiment.metrics, seen)
                new_secondary, secondary_changed = _dedupe_metrics(experiment.metrics_secondary, seen)

                if not (primary_changed or secondary_changed):
                    # Reached either because rows changed between the SELECT
                    # and now, or because the only duplication is across two
                    # saved metrics — which this command can't fix (it only
                    # rewrites inline metrics, treating saved-metric uuids as
                    # fixed points). Skip and warn so re-runs aren't expected
                    # to drive the affected count to zero in that case.
                    skipped += 1
                    logger.warning(
                        "experiment_metric_uuid_dedupe_skipped",
                        experiment_id=experiment.id,
                        reason="no_inline_change",
                    )
                    continue

                new_primary_uuids: set[str] = {uuid for m in (new_primary or []) if (uuid := m.get("uuid"))}
                new_secondary_uuids: set[str] = {uuid for m in (new_secondary or []) if (uuid := m.get("uuid"))}

                new_primary_ordering = _reconcile_ordering(
                    experiment.primary_metrics_ordered_uuids,
                    original_primary_uuids,
                    new_primary_uuids,
                    saved_metric_uuids,
                )
                new_secondary_ordering = _reconcile_ordering(
                    experiment.secondary_metrics_ordered_uuids,
                    original_secondary_uuids,
                    new_secondary_uuids,
                    saved_metric_uuids,
                )

                logger.info(
                    "experiment_metric_uuid_dedupe_planned",
                    experiment_id=experiment.id,
                    primary_changed=primary_changed,
                    secondary_changed=secondary_changed,
                    dry_run=dry_run,
                )

                if dry_run:
                    updated += 1
                    continue

                experiment.metrics = new_primary
                experiment.metrics_secondary = new_secondary
                experiment.primary_metrics_ordered_uuids = new_primary_ordering
                experiment.secondary_metrics_ordered_uuids = new_secondary_ordering
                with transaction.atomic():
                    experiment.save(
                        update_fields=[
                            "metrics",
                            "metrics_secondary",
                            "primary_metrics_ordered_uuids",
                            "secondary_metrics_ordered_uuids",
                        ]
                    )
                updated += 1
            except Exception as e:
                failed += 1
                logger.error(
                    "experiment_metric_uuid_dedupe_failed",
                    experiment_id=experiment.id,
                    error=str(e),
                    exc_info=True,
                )

        verb = "Would update" if dry_run else "Updated"
        suffix = f" {skipped} skipped (saved-metric-only duplicates, not fixable here)." if skipped else ""
        self.stdout.write(f"{verb} {updated} experiments. {failed} failed.{suffix}")
