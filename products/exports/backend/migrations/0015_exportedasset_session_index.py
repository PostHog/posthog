import django.db.models.fields.json
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0014_validate_subscription_context_team_fk"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="exportedasset",
            index=models.Index(
                models.F("team_id"),
                django.db.models.fields.json.KeyTransform("session_recording_id", "export_context"),
                name="exportedasset_session",
            ),
        ),
        SafeRemoveIndexConcurrently(model_name="exportedasset", name="exportedasset_system_session"),
    ]
