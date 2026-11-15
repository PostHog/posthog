from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    # 0106 removed the model from state and dropped its scanner foreign key.
    dependencies = [
        ("replay_vision", "0115_untrack_media_clip_fields"),
    ]

    operations = [
        SafeDropTable("replay_vision_replayscannerpromptsuggestion"),
    ]
