from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("workflows", "0027_hogflow_key"),
    ]

    operations = [
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
