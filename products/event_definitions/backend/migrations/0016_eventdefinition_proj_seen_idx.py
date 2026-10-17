from django.db import migrations, models
from django.db.models import F
from django.db.models.functions import Coalesce

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0015_drop_index_property_def_query"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                Coalesce("project_id", "team_id", output_field=models.BigIntegerField()),
                F("last_seen_at").desc(nulls_last=True),
                name="posthog_eventdef_proj_seen_idx",
            ),
        ),
    ]
