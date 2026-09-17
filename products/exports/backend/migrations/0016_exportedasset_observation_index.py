import django.db.models.fields.json
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0015_exportedasset_session_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="exportedasset",
            index=models.Index(
                models.F("team_id"),
                django.db.models.fields.json.KeyTransform("observation_id", "export_context"),
                name="exportedasset_observation",
            ),
        ),
    ]
