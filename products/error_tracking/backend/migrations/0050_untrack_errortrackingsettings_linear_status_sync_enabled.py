from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0049_externalreference_integration_context_id_index"),
    ]

    operations = [
        # The column keeps its database default, so inserts that no longer name it still succeed.
        untrack_field("errortrackingsettings", "linear_status_sync_enabled"),
    ]
