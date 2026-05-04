from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0003_eventdefinition_promoted_property"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(fields=["team_id", "name"], name="posthog_eventdef_team_name_idx"),
        ),
    ]
