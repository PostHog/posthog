import time

from django.db import migrations

BATCH_SIZE = 2000


def forwards(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # Updated rows fall out of the NULL filter, so refetching advances the backfill batch by batch.
    while True:
        batch = list(
            ExternalDataSchema.objects.filter(s3_folder_name__isnull=True).only("id", "name", "sync_type_config")[
                :BATCH_SIZE
            ]
        )
        if not batch:
            break
        for schema in batch:
            storage_key = (schema.sync_type_config or {}).get("dwh_storage_key")
            # Legacy storage key when present and non-empty, else the standard value: the schema name.
            schema.s3_folder_name = storage_key if isinstance(storage_key, str) and storage_key else schema.name
        ExternalDataSchema.objects.bulk_update(batch, ["s3_folder_name"])
        time.sleep(0.1)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0010_externaldataschema_s3_folder_name"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
