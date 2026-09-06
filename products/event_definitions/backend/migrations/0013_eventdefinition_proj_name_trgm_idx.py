from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0012_propertydefinition_proj_name_trgm_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=GinIndex(
                OpClass(Coalesce(F("project_id"), F("team_id")), name="int8_ops"),
                OpClass(F("name"), name="gin_trgm_ops"),
                name="index_eventdef_proj_name_trgm",
            ),
        ),
    ]
