from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0156_untrack_replayscanner_sampling_mode"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE replay_vision_replayscanner DROP COLUMN IF EXISTS sampling_mode",
            reverse_sql="ALTER TABLE replay_vision_replayscanner ADD COLUMN IF NOT EXISTS sampling_mode varchar(20) NOT NULL DEFAULT 'comprehensive'",
        ),
    ]
