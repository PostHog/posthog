from django.db import migrations


def forwards(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    # 0024 defaulted every row to True. Existing synced sources stay opt-in: disable them so the
    # capability gate only lights up sources a user explicitly enables. Direct sources keep True.
    ExternalDataSource.objects.filter(access_method="warehouse").update(direct_query_enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0024_externaldatasource_direct_query_enabled"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
