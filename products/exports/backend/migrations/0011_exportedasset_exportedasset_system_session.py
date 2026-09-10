import django.db.models.fields.json
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0010_alter_subscription_target_type"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="exportedasset",
            index=models.Index(
                models.F("team_id"),
                django.db.models.fields.json.KeyTransform("session_recording_id", "export_context"),
                condition=models.Q(("is_system", True)),
                name="exportedasset_system_session",
            ),
        ),
    ]
