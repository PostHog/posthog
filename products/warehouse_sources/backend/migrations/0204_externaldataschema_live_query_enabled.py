from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0203_externaldataschema_auto_disabled_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="live_query_enabled",
            field=models.BooleanField(
                db_default=False,
                default=False,
                help_text="Whether this table is queryable live on a synced source with live queries on, without syncing it. Synced tables are always queryable live.",
            ),
        ),
    ]
