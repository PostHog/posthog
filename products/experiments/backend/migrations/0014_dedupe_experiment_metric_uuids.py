from copy import deepcopy
from uuid import uuid4

from django.db import connection, migrations, transaction

import structlog

logger = structlog.get_logger(__name__)

# Returns experiment ids that have at least one duplicated metric uuid. A uuid
# is considered duplicated if it appears more than once across the union of:
#   - inline primary `metrics` array
#   - inline secondary `metrics_secondary` array
#   - any attached saved metric's `query.uuid`
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


def _dedupe_metrics(metrics, seen: set[str]) -> tuple[list, dict[str, str], bool]:
    """Walk ``metrics`` in order. The first time a uuid is seen it's kept; any
    later occurrence (within this list or already present in ``seen``) is
    regenerated. Returns the prepared list, an old→new remap for regenerated
    uuids, and whether anything changed.
    """
    if not metrics:
        return metrics or [], {}, False
    prepared = deepcopy(metrics)
    remap: dict[str, str] = {}
    changed = False
    for metric in prepared:
        original = metric.get("uuid")
        if not original or original in seen:
            new_uuid = str(uuid4())
            metric["uuid"] = new_uuid
            if original:
                remap[original] = new_uuid
            seen.add(new_uuid)
            changed = True
        else:
            seen.add(original)
    return prepared, remap, changed


def _append_new_uuids(ordering, remap: dict[str, str]):
    """Append regenerated uuids to ``ordering`` while keeping the original kept
    uuids (and any unrelated saved-metric uuids) in place.

    The incumbent uuid is preserved by dedup, so any existing reference to it
    in the ordering array remains valid — we only need to add the new uuids
    produced for the duplicates. This mirrors what
    ``_sync_ordering_with_metric_changes`` does on the live update path.
    """
    if not remap:
        return ordering
    current = list(ordering or [])
    for new_uuid in remap.values():
        if new_uuid not in current:
            current.append(new_uuid)
    return current


def dedupe_forwards(apps, schema_editor):
    """Backfill: dedupe metric uuids on the experiments that need it.

    Avoids scanning every experiment by pre-filtering at the DB level for rows
    that have at least one duplicated metric uuid. For each affected row the
    first occurrence of a uuid (within primary + secondary, in that order)
    keeps it — preserving any ExperimentMetricResult rows attached to that
    uuid and any saved-metric link that references the same uuid. Later
    occurrences get fresh uuids that are appended to the ordering array.
    """
    Experiment = apps.get_model("experiments", "Experiment")
    ExperimentToSavedMetric = apps.get_model("experiments", "ExperimentToSavedMetric")

    with connection.cursor() as cursor:
        cursor.execute(_AFFECTED_IDS_SQL)
        affected_ids = sorted({row[0] for row in cursor.fetchall()})

    if not affected_ids:
        logger.info("experiment_metric_uuid_dedupe_skipped_no_affected_rows")
        return

    logger.info("experiment_metric_uuid_dedupe_started", affected_count=len(affected_ids))

    # Chunk the ids so each `WHERE id IN (...)` stays bounded and memory is
    # controlled even when the affected set is large.
    CHUNK = 500
    for start in range(0, len(affected_ids), CHUNK):
        chunk_ids = affected_ids[start : start + CHUNK]
        qs = Experiment.objects.filter(id__in=chunk_ids).only(
            "id",
            "metrics",
            "metrics_secondary",
            "primary_metrics_ordered_uuids",
            "secondary_metrics_ordered_uuids",
        )
        # Pre-fetch saved-metric uuids for the chunk so we can seed each
        # experiment's dedup set without N+1 queries.
        saved_uuids_by_experiment: dict[int, set[str]] = {}
        links = (
            ExperimentToSavedMetric.objects.filter(experiment_id__in=chunk_ids)
            .select_related("saved_metric")
            .only("experiment_id", "saved_metric__query")
        )
        for link in links:
            sm = link.saved_metric
            if sm and sm.query:
                uuid = sm.query.get("uuid")
                if uuid:
                    saved_uuids_by_experiment.setdefault(link.experiment_id, set()).add(uuid)

        for experiment in qs.iterator():
            try:
                # Seed with saved-metric uuids: inline metrics colliding with one
                # must be regenerated so each ordering entry resolves uniquely.
                seen: set[str] = set(saved_uuids_by_experiment.get(experiment.id, set()))
                new_primary, primary_remap, primary_changed = _dedupe_metrics(experiment.metrics or [], seen)
                new_secondary, secondary_remap, secondary_changed = _dedupe_metrics(
                    experiment.metrics_secondary or [], seen
                )

                if not (primary_changed or secondary_changed):
                    # Should be unreachable given the pre-filter, but guard anyway
                    # in case rows changed between the SELECT and now.
                    continue

                experiment.metrics = new_primary
                experiment.metrics_secondary = new_secondary
                experiment.primary_metrics_ordered_uuids = _append_new_uuids(
                    experiment.primary_metrics_ordered_uuids, primary_remap
                )
                experiment.secondary_metrics_ordered_uuids = _append_new_uuids(
                    experiment.secondary_metrics_ordered_uuids, secondary_remap
                )
                with transaction.atomic():
                    experiment.save(
                        update_fields=[
                            "metrics",
                            "metrics_secondary",
                            "primary_metrics_ordered_uuids",
                            "secondary_metrics_ordered_uuids",
                        ]
                    )
                logger.info(
                    "experiment_metric_uuids_deduped",
                    experiment_id=experiment.id,
                    primary_remap=primary_remap,
                    secondary_remap=secondary_remap,
                )
            except Exception as e:
                logger.error(
                    "experiment_metric_uuid_dedupe_failed",
                    experiment_id=experiment.id,
                    error=str(e),
                    exc_info=True,
                )
                continue


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("experiments", "0013_teamexperimentsconfig_default_minimum_detectable_effect"),
    ]

    operations = [
        migrations.RunPython(dedupe_forwards, migrations.RunPython.noop, elidable=True),
    ]
