from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0179_pin_omnisend_null_api_version_to_v3")]

    operations = [
        migrations.AlterField(
            model_name="datawarehousetable",
            name="row_count",
            field=models.BigIntegerField(help_text="How many rows are currently synced in this table", null=True),
        ),
    ]
