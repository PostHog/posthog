from django.db import migrations, models
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0010_propertydefinition_warehouse_origin"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="propertydefinition",
            index=models.Index(
                Coalesce(F("project_id"), F("team_id")),
                F("type"),
                Coalesce(F("group_type_index"), -1),
                F("name"),
                condition=models.Q(("name__startswith", "$feature/")),
                name="index_propdef_feature_flag",
            ),
        ),
    ]
