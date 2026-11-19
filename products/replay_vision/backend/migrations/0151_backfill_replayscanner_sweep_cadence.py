from django.db import migrations, transaction
from django.utils import timezone

from products.replay_vision.backend.temporal.read_meter_types import current_sweep_throttle_factor

_BATCH_SIZE = 500


def backfill_sweep_cadence(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    now = timezone.now()
    last_pk = None
    while True:
        rows = ReplayScanner.objects.order_by("pk")
        if last_pk is not None:
            rows = rows.filter(pk__gt=last_pk)
        batch = list(
            rows.only(
                "id",
                "last_found_candidates_at",
                "fast_read_bytes_by_hour",
                "sweep_read_bytes_by_hour",
                "sweep_throttle_factor",
            )[:_BATCH_SIZE]
        )
        if not batch:
            return
        last_pk = batch[-1].pk
        changed = []
        for scanner in batch:
            # Without it every existing scanner reads as never having found anything and drops to the slowest sweep at once.
            found_at = scanner.last_found_candidates_at or now
            # Until the hourly read meter runs, a scanner over its read budget would otherwise sweep at the busy cadence.
            factor = current_sweep_throttle_factor(
                scanner.fast_read_bytes_by_hour, scanner.sweep_read_bytes_by_hour, None, now
            )
            if (found_at, factor) != (scanner.last_found_candidates_at, scanner.sweep_throttle_factor):
                scanner.last_found_candidates_at, scanner.sweep_throttle_factor = found_at, factor
                changed.append(scanner)
        # Each batch commits alone, so a scanner edit or admission waits on at most one batch's row locks.
        with transaction.atomic():
            ReplayScanner.objects.bulk_update(changed, ["last_found_candidates_at", "sweep_throttle_factor"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0150_replay_scanner_sweep_cadence"),
    ]

    operations = [
        migrations.RunPython(backfill_sweep_cadence, migrations.RunPython.noop, elidable=True),
    ]
