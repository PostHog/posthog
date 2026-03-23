import random
from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def backfill_last_used(apps, schema_editor):
    ErrorTrackingSymbolSet = apps.get_model("error_tracking", "ErrorTrackingSymbolSet")
    batch_size = 500

    while True:
        batch = list(ErrorTrackingSymbolSet.objects.filter(last_used__isnull=True)[:batch_size])
        if not batch:
            break

        now = timezone.now()
        for symbol_set in batch:
            symbol_set.last_used = now + timedelta(days=random.randint(0, 15))

        ErrorTrackingSymbolSet.objects.bulk_update(batch, ["last_used"])


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0013_spike_events"),
    ]

    operations = [
        migrations.RunPython(backfill_last_used, reverse_code=migrations.RunPython.noop),
    ]
