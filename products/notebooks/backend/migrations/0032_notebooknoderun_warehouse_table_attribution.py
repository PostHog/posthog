from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("notebooks", "0031_notebooknoderun_warehouse_table_name")]

    operations = [
        migrations.AddField(
            model_name="notebooknoderun",
            name="warehouse_table_attribution",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
