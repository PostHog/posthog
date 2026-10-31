from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0188_reset_trunkio_v2_failing_tests")]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="masked_columns",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
