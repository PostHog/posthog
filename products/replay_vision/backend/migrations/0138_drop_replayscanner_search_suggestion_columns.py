from django.db import migrations

_COLUMNS = {
    "search_suggestions": "jsonb",
    "search_suggestions_watermark": "timestamptz",
    "search_suggestions_generated_at": "timestamptz",
    "search_last_viewed_at": "timestamptz",
}


class Migration(migrations.Migration):
    # 0137 untracked the columns. Each table drops in its own migration, so one table's lock never waits on the other's.
    dependencies = [
        ("replay_vision", "0137_retire_feed_rankers_schema"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "replay_vision_replayscanner" '
                    + ", ".join(f'DROP COLUMN IF EXISTS "{column}"' for column in _COLUMNS),
                    reverse_sql='ALTER TABLE "replay_vision_replayscanner" '
                    + ", ".join(
                        f'ADD COLUMN IF NOT EXISTS "{column}" {kind} NULL' for column, kind in _COLUMNS.items()
                    ),
                ),
            ],
        ),
    ]
