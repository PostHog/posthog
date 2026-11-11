from django.db import migrations


class Migration(migrations.Migration):
    # 0137 untracked the column. Each table drops in its own migration, so one table's lock never waits on the other's.
    dependencies = [
        ("replay_vision", "0139_drop_teamreplayvisionconfig_search_suggestion_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "replay_vision_replayobservationmedia" DROP COLUMN IF EXISTS "rec_start_ms"',
                    reverse_sql='ALTER TABLE "replay_vision_replayobservationmedia" ADD COLUMN IF NOT EXISTS "rec_start_ms" integer NULL',
                ),
            ],
        ),
    ]
