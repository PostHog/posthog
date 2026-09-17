from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0124_drop_retired_code_home_tables"),
    ]

    # State-only removal: Desktop loops moved onto workflows and the loops API is gone, but
    # posthog_task_loop, posthog_task_looptrigger, posthog_task_loop_fire and posthog_task.loop_id
    # stay in place for a SafeDropTable migration after a deploy cycle.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveIndex(model_name="task", name="posthog_task_loop_idx")],
        ),
        untrack_field("task", "loop", database_operations=[DropForeignKey("posthog_task", column="loop_id")]),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="LoopFire"),
                migrations.DeleteModel(name="LoopTrigger"),
                migrations.DeleteModel(name="Loop"),
            ],
            database_operations=[
                DropForeignKey("posthog_task_loop", column="sandbox_environment_id"),
                DropForeignKey("posthog_task_loop_trigger", column="loop_id"),
                DropForeignKey("posthog_task_loop_fire", column="loop_trigger_id"),
            ],
        ),
    ]
