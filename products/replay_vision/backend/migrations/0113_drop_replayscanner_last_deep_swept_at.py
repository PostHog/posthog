from django.db import migrations


class Migration(migrations.Migration):
    # 0078 untracked the column. Each table drops in its own migration, so one table's lock never waits on the other's.
    dependencies = [
        ("replay_vision", "0112_drop_replayquotagrant_table"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "replay_vision_replayscanner" DROP COLUMN IF EXISTS "last_deep_swept_at"',
                    reverse_sql='ALTER TABLE "replay_vision_replayscanner" ADD COLUMN IF NOT EXISTS "last_deep_swept_at" timestamptz NULL',
                ),
            ],
        ),
    ]
