from django.db import migrations


def forwards(apps, schema_editor):
    # ExternalDataSource is one row per configured source (thousands, not events-scale), so a
    # single update is safe — no batching needed.
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    ExternalDataSource.objects.filter(access_method="warehouse", direct_query_enabled=True).update(
        direct_query_enabled=False
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0060_direct_query_enabled_default_false")]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
