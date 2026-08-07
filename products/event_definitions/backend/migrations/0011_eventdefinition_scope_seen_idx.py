from django.db import migrations, models
from django.db.models.functions import Coalesce

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0010_propertydefinition_warehouse_origin"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                Coalesce("project_id", "team_id"),
                "last_seen_at",
                name="posthog_eventdef_scope_seen_ix",
            ),
        ),
    ]
