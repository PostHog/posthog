from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY index creation can't run inside a transaction.
    atomic = False

    dependencies = [
        ("tasks", "0039_dedupe_sandbox_environments"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="sandboxenvironment",
                    constraint=models.UniqueConstraint(
                        fields=["team", "name"],
                        name="unique_sandbox_env_per_team_name",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_sandbox_env_per_team_name",
                    table_name="posthog_sandbox_environment",
                    columns="(team_id, name)",
                    unique=True,
                ),
            ],
        ),
    ]
