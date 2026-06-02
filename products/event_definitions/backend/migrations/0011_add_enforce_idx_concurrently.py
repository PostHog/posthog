from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0010_enforce_mode_and_schema_version"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                condition=models.Q(("enforcement_mode__in", ["reject", "enforce"])),
                fields=["team_id"],
                name="posthog_eventdef_enforce_idx",
            ),
        ),
    ]
