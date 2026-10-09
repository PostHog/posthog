from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0136_untrack_task_loop"),
    ]

    operations = [
        # The tables stay until a later SafeDropTable. Drop their database-enforced foreign keys as
        # Django can no longer cascade through models removed from state.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="LoopFire"),
                migrations.DeleteModel(name="LoopTrigger"),
                migrations.DeleteModel(name="Loop"),
            ],
            database_operations=[
                DropForeignKey("posthog_task_loop_fire", column="loop_trigger_id"),
                DropForeignKey("posthog_task_loop_trigger", column="loop_id"),
                DropForeignKey("posthog_task_loop", column="sandbox_environment_id"),
            ],
        ),
    ]
