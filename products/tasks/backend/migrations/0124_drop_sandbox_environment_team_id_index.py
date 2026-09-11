import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("tasks", "0123_alter_sandboxsnapshot_integration"),
    ]

    operations = [
        # Django's automatic ForeignKey index. The (team, created_by) composite index
        # declared on SandboxEnvironment.Meta leads with team_id, so every team-only
        # read uses that composite as a prefix and this single-column index serves no read.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="sandboxenvironment",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_sandbox_environment_team_id_d94b6a9a",
                    table_name="posthog_sandbox_environment",
                    columns="(team_id)",
                ),
            ],
        ),
    ]
