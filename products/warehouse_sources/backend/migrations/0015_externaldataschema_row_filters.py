from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0014_backfill_externaldataschema_s3_folder_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="row_filters",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
