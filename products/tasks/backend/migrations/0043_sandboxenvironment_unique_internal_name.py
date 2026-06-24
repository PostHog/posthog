from django.db import migrations, models

from posthog.migration_helpers.concurrent_index import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0042_dedupe_internal_sandbox_envs"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="sandboxenvironment",
                    constraint=models.UniqueConstraint(
                        fields=["team", "name"],
                        condition=models.Q(internal=True),
                        name="unique_internal_sandbox_env_team_name",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_internal_sandbox_env_team_name",
                    table_name="posthog_sandbox_environment",
                    columns="(team_id, name)",
                    unique=True,
                    where='WHERE "internal"',
                ),
            ],
        ),
    ]
