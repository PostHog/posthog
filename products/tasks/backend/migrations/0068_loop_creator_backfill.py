from django.db import migrations
from django.db.models import F


def backfill_creator(apps, schema_editor):
    Loop = apps.get_model("tasks", "Loop")
    Loop.objects.filter(creator_id__isnull=True).update(creator_id=F("created_by_id"))


class Migration(migrations.Migration):
    # Data migration kept apart from the AddField in 0067 so the schema change never shares a
    # transaction (and its locks) with the backfill.
    dependencies = [
        ("tasks", "0067_loop_creator"),
    ]

    operations = [
        migrations.RunPython(backfill_creator, migrations.RunPython.noop, elidable=True),
    ]
