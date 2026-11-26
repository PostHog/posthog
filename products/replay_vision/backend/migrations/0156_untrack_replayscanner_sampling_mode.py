from django.db import migrations

from posthog.migration_helpers.untrack_field import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0155_replay_scope_indexes"),
    ]

    operations = [
        untrack_field("replayscanner", "sampling_mode"),
    ]
