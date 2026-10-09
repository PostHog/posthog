from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0136_untrack_task_loop"),
    ]

    operations = [
        # The tables stay until a later SafeDropTable. sandbox_environment_id is their only real key into a
        # live table, so it goes now or deleting a sandbox environment fails at COMMIT.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="LoopFire"),
                migrations.DeleteModel(name="LoopTrigger"),
                migrations.DeleteModel(name="Loop"),
            ],
            database_operations=[DropForeignKey("posthog_task_loop", column="sandbox_environment_id")],
        ),
    ]
