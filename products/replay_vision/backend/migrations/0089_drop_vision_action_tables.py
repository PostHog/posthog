# Generated manually - drops the legacy vision action tables.
# Second step after 0086 removed both models from Django state.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0088_remap_scanner_models_gemini_3_8"),
    ]

    # Both tables carry foreign keys to posthog_team and posthog_user, so dropping them takes a
    # brief ACCESS EXCLUSIVE lock on those hot tables to remove the referential triggers. The local
    # timeout keeps a lost lock race from queueing behind in-flight traffic; bin/migrate retries.
    operations = [
        # The run table goes first: its foreign key references the action table.
        migrations.RunSQL(
            sql="SET LOCAL lock_timeout = '2s'; DROP TABLE IF EXISTS replay_vision_visionactionrun;",
            reverse_sql="",  # No reverse - the rows are gone with the table.
        ),
        migrations.RunSQL(
            sql="SET LOCAL lock_timeout = '2s'; DROP TABLE IF EXISTS replay_vision_visionaction;",
            reverse_sql="",
        ),
    ]
