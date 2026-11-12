from django.db import migrations
from django.utils import timezone

from products.replay_vision.backend.temporal.read_meter_types import current_sweep_throttle_factor

_BATCH_SIZE = 500


def backfill_sweep_cadence(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    now = timezone.now()
    # Without it every existing scanner reads as never having found anything and drops to the slowest sweep at once.
    ReplayScanner.objects.filter(last_found_candidates_at__isnull=True).update(last_found_candidates_at=now)

    # Until the hourly read meter runs, a scanner over its read budget would otherwise sweep at the busy cadence.
    throttled = []
    for scanner in ReplayScanner.objects.only(
        "id", "fast_read_bytes_by_hour", "sweep_read_bytes_by_hour", "sweep_throttle_factor"
    ).iterator(chunk_size=_BATCH_SIZE):
        factor = current_sweep_throttle_factor(
            scanner.fast_read_bytes_by_hour, scanner.sweep_read_bytes_by_hour, None, now
        )
        if factor != scanner.sweep_throttle_factor:
            scanner.sweep_throttle_factor = factor
            throttled.append(scanner)
    ReplayScanner.objects.bulk_update(throttled, ["sweep_throttle_factor"], batch_size=_BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0149_replay_scanner_sweep_cadence"),
    ]

    operations = [
        migrations.RunPython(backfill_sweep_cadence, migrations.RunPython.noop, elidable=True),
    ]
