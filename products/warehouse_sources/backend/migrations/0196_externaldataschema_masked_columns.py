from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0195_repin_rippling_api_version_v2")]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="masked_columns",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
