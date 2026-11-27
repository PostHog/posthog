from django.db import migrations

# Apollo's account search returns no `updated_at`, the only incremental field ever offered for
# the `accounts` table, so every incremental or append sync of it failed at cursor extraction.
# The source now offers full refresh only for this table. Move the stored schemas to it: such a
# sync could never complete, so these schemas hold no cursor to lose.


def forwards(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")
    # `_base_manager` so soft-deleted rows are moved too: an undelete would otherwise bring the
    # unusable sync type back.
    ExternalDataSchema._base_manager.filter(
        source__source_type="Apollo",
        name="accounts",
        sync_type__in=("incremental", "append"),
    ).update(sync_type="full_refresh")


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0207_externaldataschema_last_checked_at")]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
