from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    """Index builds only. CREATE INDEX CONCURRENTLY cannot run inside a transaction, which is the one
    reason this migration gives up atomicity; the helper is idempotent under bin/migrate retries.

    A conditional UniqueConstraint is a partial unique index in Postgres, which has no NOT VALID form,
    so the index is built here and the constraint recorded state-only (the same shape as 0030).
    Django's RemoveConstraint emits DROP INDEX for a conditional constraint, so state and database
    agree about what these objects are.
    """

    atomic = False

    dependencies = [
        ("replay_vision", "0059_replayscanner_origin"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="replayscanner",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("origin", "configured")),
                        fields=("team", "name"),
                        name="replay_scanner_unique_configured_team_name",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="replay_scanner_unique_configured_team_name",
                    table_name="replay_vision_replayscanner",
                    columns='("team_id", "name")',
                    unique=True,
                    where="WHERE \"origin\" = 'configured'",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="replayscanner",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("origin", "inline")),
                        fields=("team", "inline_key"),
                        name="replay_scanner_unique_team_inline_key",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="replay_scanner_unique_team_inline_key",
                    table_name="replay_vision_replayscanner",
                    columns='("team_id", "inline_key")',
                    unique=True,
                    where="WHERE \"origin\" = 'inline'",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="replayscanner",
                    index=models.Index(
                        condition=models.Q(("origin", "inline")),
                        fields=["created_at"],
                        name="rl_inline_created_idx",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="rl_inline_created_idx",
                    table_name="replay_vision_replayscanner",
                    columns='("created_at")',
                    where="WHERE \"origin\" = 'inline'",
                ),
            ],
        ),
    ]
