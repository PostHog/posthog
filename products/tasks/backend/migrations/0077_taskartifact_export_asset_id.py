from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0076_taskrun_task_run_sd_branch_idx")]

    operations = [
        migrations.AddField(
            model_name="taskartifact",
            name="export_asset_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
