from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Required by CreateIndexConcurrently, and why the column it indexes is added in 0026 instead.
    atomic = False

    dependencies = [
        ("workflows", "0027_hogflow_key"),
    ]

    operations = [
        # A partial unique constraint compiles to a partial unique index, which Django's
        # AddConstraint builds under an ACCESS EXCLUSIVE lock. Build the index concurrently instead
        # and record only the constraint in Django's state. The condition keeps the many key-less
        # rows out of the index, and keeps the state's own SQL identical to what is built here.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="hogflow",
                    constraint=models.UniqueConstraint(
                        fields=("team", "key"),
                        condition=models.Q(("key__isnull", False)),
                        name="unique_key_for_team",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_key_for_team",
                    table_name="posthog_hogflow",
                    columns="(team_id, key)",
                    unique=True,
                    where='WHERE "key" IS NOT NULL',
                ),
            ],
        ),
    ]
