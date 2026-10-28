from django.db import migrations


class Migration(migrations.Migration):
    # 0099 untracked both columns. One ALTER TABLE takes the table lock once.
    dependencies = [
        ("replay_vision", "0113_drop_replayscanner_last_deep_swept_at"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "replay_vision_replayobservation" '
                        'DROP COLUMN IF EXISTS "media_render_attempts", '
                        'DROP COLUMN IF EXISTS "media_render_attempted_at"'
                    ),
                    reverse_sql=(
                        'ALTER TABLE "replay_vision_replayobservation" '
                        'ADD COLUMN IF NOT EXISTS "media_render_attempts" smallint NOT NULL DEFAULT 0, '
                        'ADD COLUMN IF NOT EXISTS "media_render_attempted_at" timestamptz NULL'
                    ),
                ),
            ],
        ),
    ]
