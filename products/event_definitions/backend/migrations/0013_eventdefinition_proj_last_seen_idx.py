from django.db import migrations, models
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0012_alter_eventdefinition_project_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                Coalesce(F("project_id"), F("team_id")),
                F("last_seen_at"),
                name="eventdef_proj_last_seen_idx",
            ),
        ),
    ]
