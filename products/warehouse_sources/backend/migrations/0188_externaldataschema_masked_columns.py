from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0187_repin_teamtailor_api_version")]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="masked_columns",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
