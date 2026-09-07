import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0117_task_set_null_cascade_indexes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="sandboxenvironment",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_sandbox_environment_team_id_d94b6a9a",
                    table_name="posthog_sandbox_environment",
                    columns='("team_id")',
                ),
            ],
        ),
    ]
