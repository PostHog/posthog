from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0010_propertydefinition_warehouse_origin"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(fields=["team_id", "-last_seen_at"], name="posthog_eventdef_team_seen_idx"),
        ),
    ]
