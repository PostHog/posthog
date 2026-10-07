from django.db import migrations


class Migration(migrations.Migration):
    # 0078 untracked last_deep_swept_at and 0099 untracked the media render columns.
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
                migrations.RunSQL(
                    sql='ALTER TABLE "replay_vision_replayobservation" DROP COLUMN IF EXISTS "media_render_attempts"',
                    reverse_sql='ALTER TABLE "replay_vision_replayobservation" ADD COLUMN IF NOT EXISTS "media_render_attempts" smallint NOT NULL DEFAULT 0',
                ),
                migrations.RunSQL(
                    sql='ALTER TABLE "replay_vision_replayobservation" DROP COLUMN IF EXISTS "media_render_attempted_at"',
                    reverse_sql='ALTER TABLE "replay_vision_replayobservation" ADD COLUMN IF NOT EXISTS "media_render_attempted_at" timestamptz NULL',
                ),
            ],
        ),
    ]
