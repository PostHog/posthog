from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0185_externaldatadestination_health")]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="masked_columns",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
