from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("notebooks", "0030_notebook_app_layout")]

    operations = [
        migrations.AddField(
            model_name="notebooknoderun",
            name="warehouse_table_name",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="notebooknoderun",
            name="input_run_ids",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
