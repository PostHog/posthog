import time

from django.db import migrations, models

BATCH_SIZE = 2000


def forwards(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    # `direct_query_enabled` shipped defaulting to True, so every synced source created since then was
    # silently opted in. Direct connect stays off unless a user turns it on, so opt those synced sources
    # back out; pure direct sources ignore the flag. Batch so we never hold row locks across the whole
    # table at once — updated rows fall out of the filter, advancing the loop.
    while True:
        batch_ids = list(
            ExternalDataSource.objects.filter(access_method="warehouse", direct_query_enabled=True).values_list(
                "id", flat=True
            )[:BATCH_SIZE]
        )
        if not batch_ids:
            break
        ExternalDataSource.objects.filter(id__in=batch_ids).update(direct_query_enabled=False)
        time.sleep(0.1)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("warehouse_sources", "0057_alter_externaldatasource_source_type_and_more")]

    operations = [
        migrations.AlterField(
            model_name="externaldatasource",
            name="direct_query_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
