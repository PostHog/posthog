from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0041_taskrun_created_at_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["team", "-created_at", "-id"], name="posthog_task_team_created_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["team", "created_by", "-created_at", "-id"], name="posthog_task_team_creator_idx"
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(fields=["task", "-created_at", "-id"], name="task_run_task_created_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                fields=["team", "stage", "task"],
                name="task_run_team_stage_task_idx",
                condition=models.Q(stage__isnull=False),
            ),
        ),
    ]
