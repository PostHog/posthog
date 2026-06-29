from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0042_task_list_perf_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="codeworkstream",
            name="auto_run_state",
            field=models.JSONField(
                default=dict,
                help_text=(
                    "Per-action auto-run markers ({action_id: {fired_at, task_id, situation}}) so a "
                    "fired auto action isn't relaunched every cycle. Owned by the auto-run step, not the rebuild."
                ),
            ),
        ),
    ]
