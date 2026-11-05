from django.db import migrations


def repair_legacy_full_sync_type(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")
    # `_base_manager` so soft-deleted rows are repaired too: an undelete would otherwise
    # bring the unusable value back.
    ExternalDataSchema._base_manager.filter(sync_type="full").update(sync_type="full_refresh")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0172_migrate_apple_search_ads_job_inputs_to_auth_method"),
    ]

    operations = [
        migrations.RunPython(repair_legacy_full_sync_type, migrations.RunPython.noop),
    ]
