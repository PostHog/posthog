from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Required by CreateIndexConcurrently, and why the column it indexes is added in 0026 instead.
    atomic = False

    dependencies = [
        ("workflows", "0027_hogflow_key"),
    ]

    operations = [
        # A unique constraint compiles to a unique index, which Django's AddConstraint builds under
        # an ACCESS EXCLUSIVE lock. Build the index concurrently instead and record only the
        # constraint in Django's state. No WHERE clause: Postgres treats NULLs as distinct, so the
        # existing key-less rows cannot collide with each other.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="hogflow",
                    constraint=models.UniqueConstraint(fields=("team", "key"), name="unique_key_for_team"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_key_for_team",
                    table_name="posthog_hogflow",
                    columns="(team_id, key)",
                    unique=True,
                ),
            ],
        ),
    ]
