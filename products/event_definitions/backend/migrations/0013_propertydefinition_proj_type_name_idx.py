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
            model_name="propertydefinition",
            index=models.Index(
                Coalesce(F("project_id"), F("team_id")),
                F("type"),
                Coalesce(F("group_type_index"), -1),
                F("name"),
                name="index_propdef_proj_type_name",
            ),
        ),
    ]
