from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("tasks", "0098_task_hog_flow_id_task_origin_key_and_more")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["hog_flow_id", "-created_at"], name="posthog_task_hog_flow_idx"),
        ),
        # A partial unique constraint compiles to a partial unique index, which Django's
        # AddConstraint builds under an ACCESS EXCLUSIVE lock. Build the index concurrently
        # instead and record only the constraint in Django's state.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="task",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("origin_key__isnull", False)),
                        fields=("team", "origin_key"),
                        name="posthog_task_origin_key_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_task_origin_key_uniq",
                    table_name="posthog_task",
                    columns="(team_id, origin_key)",
                    unique=True,
                    where="WHERE origin_key IS NOT NULL",
                ),
            ],
        ),
    ]
