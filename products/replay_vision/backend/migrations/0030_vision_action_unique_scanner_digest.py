from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("replay_vision", "0029_visionaction_is_scanner_digest"),
    ]

    operations = [
        # A conditional UniqueConstraint is a partial unique index in Postgres, which has no
        # NOT VALID form — so build the index concurrently (lock-free) and record the constraint
        # state-only. The helper is idempotent under bin/migrate retries.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="visionaction",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("is_scanner_digest", True)),
                        fields=("scanner",),
                        name="vision_action_unique_scanner_digest",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="vision_action_unique_scanner_digest",
                    table_name="replay_vision_visionaction",
                    columns='("scanner_id")',
                    unique=True,
                    where='WHERE "is_scanner_digest"',
                ),
            ],
        ),
    ]
