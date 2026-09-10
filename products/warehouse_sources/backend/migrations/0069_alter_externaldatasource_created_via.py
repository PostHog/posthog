from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0068_backfill_direct_query_enabled_false"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externaldatasource",
            name="created_via",
            field=models.CharField(
                blank=True,
                choices=[
                    ("web", "web"),
                    ("api", "api"),
                    ("mcp", "mcp"),
                    ("wizard", "wizard"),
                    ("self_driving", "self_driving"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
