import time

from django.db import migrations

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

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
            legacy_key = (schema.sync_type_config or {}).get("dwh_storage_key")
            # Legacy storage key when present, else the schema name. The S3 folder is the *normalized*
            # identifier (readers normalize before building the path), so store the normalized form —
            # not the raw name, which would point at a folder that doesn't exist for e.g. "My Table".
            raw = legacy_key if isinstance(legacy_key, str) and legacy_key else schema.name
            schema.s3_folder_name = NamingConvention.normalize_identifier(raw)
        ExternalDataSchema.objects.bulk_update(batch, ["s3_folder_name"])
        time.sleep(0.1)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0013_externaldataschema_s3_folder_name"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
