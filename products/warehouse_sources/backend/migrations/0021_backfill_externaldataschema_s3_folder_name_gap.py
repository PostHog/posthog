import time

from django.db import migrations

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

BATCH_SIZE = 2000


def forwards(apps, schema_editor):
    # Rows created after the column shipped but before `save()` started populating it have a NULL
    # `s3_folder_name`. Re-run the same backfill to fill them; the model's `save()` override prevents
    # any new NULLs going forward.
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

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
            raw = legacy_key if isinstance(legacy_key, str) and legacy_key else schema.name
            schema.s3_folder_name = NamingConvention.normalize_identifier(raw)
        ExternalDataSchema.objects.bulk_update(batch, ["s3_folder_name"])
        time.sleep(0.1)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0020_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
