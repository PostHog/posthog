from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.operations import BtreeGinExtension
from django.db import migrations
from django.db.models import F
from django.db.models.functions import Coalesce

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [("event_definitions", "0015_drop_index_property_def_query")]

    operations = [
        # `int8_ops` for the project column comes from btree_gin.
        BtreeGinExtension(),
        SafeAddIndexConcurrently(
            model_name="eventdefinition",
            index=GinIndex(
                OpClass(Coalesce(F("project_id"), F("team_id")), name="int8_ops"),
                OpClass(F("name"), name="gin_trgm_ops"),
                name="eventdef_proj_name_trgm",
            ),
        ),
    ]
