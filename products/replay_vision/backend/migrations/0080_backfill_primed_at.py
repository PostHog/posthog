from django.db import migrations
from django.db.models import F


def backfill_primed_at(apps, schema_editor):
    # Existing scanners were created before priming existed and have been swept for real; marking
    # them primed keeps the one-off pass strictly for scanners created after this deploy. The
    # scanner table is small (thousands of rows), so a single UPDATE is fine.
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    ReplayScanner.objects.filter(primed_at__isnull=True).update(primed_at=F("created_at"))


class Migration(migrations.Migration):
    dependencies = [("replay_vision", "0079_replayscanner_primed_at")]

    operations = [
        migrations.RunPython(backfill_primed_at, migrations.RunPython.noop, elidable=True),
    ]
