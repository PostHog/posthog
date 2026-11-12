from django.db import migrations
from django.utils import timezone


def backfill_last_found_candidates_at(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    # Without it every existing scanner reads as never having found anything and drops to the slowest sweep at once.
    ReplayScanner.objects.filter(last_found_candidates_at__isnull=True).update(last_found_candidates_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0149_replay_scanner_sweep_cadence"),
    ]

    operations = [
        migrations.RunPython(backfill_last_found_candidates_at, migrations.RunPython.noop, elidable=True),
    ]
