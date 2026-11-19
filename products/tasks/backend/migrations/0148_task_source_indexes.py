from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0147_task_source_columns"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["source_kind", "source_id", "-created_at"],
                condition=models.Q(("source_kind__isnull", False)),
                name="posthog_task_source_idx",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="task",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("idempotency_key__isnull", False)),
                        fields=("team", "idempotency_key"),
                        name="posthog_task_idempotency_key_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_task_idempotency_key_uniq",
                    table_name="posthog_task",
                    columns="(team_id, idempotency_key)",
                    unique=True,
                    where="WHERE idempotency_key IS NOT NULL",
                ),
            ],
        ),
    ]
