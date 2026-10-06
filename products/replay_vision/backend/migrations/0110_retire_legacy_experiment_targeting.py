"""Retire scanners that target an experiment through the legacy `experiment_targeting` column.

From here on only the experiment scanner type watches an experiment. Each legacy targeted scanner is
turned off, its active backfills are cancelled, and its targeting is copied into `scanner_config`
(`experiment_id`, `variants`), where the scope readers look first. Its observations' snapshots get the
same copy, so their experiment access gate keeps holding once the column goes. The column itself is
left as it is, so a pod still on the old code reads what it expects.

`update()` rather than `save()`: nothing about the scanners' config changes meaning, so no version
bump. The reconciler drops the schedules of disabled scanners, and the reaper those of cancelled
backfills.
"""

from typing import Any

from django.db import migrations
from django.utils import timezone

_BATCH_SIZE = 1000
_ACTIVE_BACKFILL_STATUSES = ("running", "paused_quota")


def _config_scope(targeting: Any) -> dict[str, Any] | None:
    if not isinstance(targeting, dict) or not isinstance(targeting.get("experiment_id"), int):
        return None
    variant = targeting.get("variant")
    return {"experiment_id": targeting["experiment_id"], "variants": [variant] if variant else None}


def retire_legacy_experiment_targeting(apps: Any, schema_editor: Any) -> None:
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayScannerBackfill = apps.get_model("replay_vision", "ReplayScannerBackfill")
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")

    retired: list[Any] = []
    legacy = ReplayScanner.objects.exclude(scanner_type="experiment").filter(
        experiment_targeting__experiment_id__isnull=False
    )
    for scanner_id, config, targeting in legacy.values_list("id", "scanner_config", "experiment_targeting"):
        scope = _config_scope(targeting)
        if scope is None:
            continue
        merged = {**(config if isinstance(config, dict) else {}), **scope}
        ReplayScanner.objects.filter(pk=scanner_id).update(enabled=False, scanner_config=merged)
        retired.append(scanner_id)

    ReplayScannerBackfill.objects.filter(scanner_id__in=retired, status__in=_ACTIVE_BACKFILL_STATUSES).update(
        status="cancelled", finished_at=timezone.now()
    )

    # Keyset batches over the primary key, so each batch commits on its own and no long lock is held.
    targeted = (
        ReplayObservation.objects.exclude(scanner_snapshot__scanner_type="experiment")
        .filter(scanner_snapshot__experiment_targeting__experiment_id__isnull=False)
        .order_by("id")
    )
    last_id = None
    while True:
        batch = targeted if last_id is None else targeted.filter(id__gt=last_id)
        rows = list(batch.values_list("id", "scanner_snapshot")[:_BATCH_SIZE])
        if not rows:
            break
        updates = []
        for observation_id, snapshot in rows:
            scope = _config_scope(snapshot.get("experiment_targeting"))
            if scope is None:
                continue
            config = snapshot.get("scanner_config") if isinstance(snapshot.get("scanner_config"), dict) else {}
            updates.append(
                ReplayObservation(
                    id=observation_id, scanner_snapshot={**snapshot, "scanner_config": {**config, **scope}}
                )
            )
        ReplayObservation.objects.bulk_update(updates, ["scanner_snapshot"])
        last_id = rows[-1][0]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0109_alter_replayobservation_error_reason"),
    ]

    operations = [
        migrations.RunPython(retire_legacy_experiment_targeting, migrations.RunPython.noop),
    ]
