from django.db import migrations


class Migration(migrations.Migration):
    # 0115 untracked the clip columns. One ALTER TABLE takes the table lock once.
    dependencies = [
        ("replay_vision", "0117_drop_replayscanner_feedback_themes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "replay_vision_replayobservationmedia" '
                        'DROP COLUMN IF EXISTS "description", '
                        'DROP COLUMN IF EXISTS "video_end_ms", '
                        'DROP COLUMN IF EXISTS "rec_end_ms"'
                    ),
                    reverse_sql=(
                        'ALTER TABLE "replay_vision_replayobservationmedia" '
                        'ADD COLUMN IF NOT EXISTS "description" text NULL, '
                        'ADD COLUMN IF NOT EXISTS "video_end_ms" integer NULL, '
                        'ADD COLUMN IF NOT EXISTS "rec_end_ms" integer NULL'
                    ),
                ),
            ],
        ),
    ]
