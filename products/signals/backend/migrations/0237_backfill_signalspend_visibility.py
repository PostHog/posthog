from django.db import migrations
from django.db.models import F


def backfill_visibility(apps, schema_editor):
    receipts = apps.get_model("signals", "SignalSpend")._base_manager.using(schema_editor.connection.alias)
    last_id = None
    while True:
        pending = receipts.filter(is_private__isnull=True)
        if last_id is not None:
            pending = pending.filter(id__gt=last_id)
        ids = list(pending.order_by("id").values_list("id", flat=True)[:1000])
        if not ids:
            return
        # The trigger classifies old receipts too; deleted owners remain unknown and fail closed.
        receipts.filter(id__in=ids, is_private__isnull=True).update(is_private=F("is_private"))
        last_id = ids[-1]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0236_snapshot_signalspend_visibility")]

    operations = [migrations.RunPython(backfill_visibility, migrations.RunPython.noop)]
