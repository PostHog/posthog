from django.db import migrations
from django.db.models import Q

# A TrunkIo source on the v2 pin used to read `FailingTests` from the v1
# `list-failing-tests` endpoint. It now reads `GET /v2/tests`, whose test ids and columns differ.
# `FailingTests` syncs incrementally and merges on `id`, so the old v1 rows would stay beside the
# new v2 rows. Stamp `reset_pipeline`, so the next sync wipes the table and rebuilds it in the v2
# shape (`handle_reset_or_full_refresh`). `UnhealthyTests` and `QuarantinedTests` are full refresh
# and replace their table on every sync, so they need no reset. A v1 pin keeps its v1 wire.
TRUNKIO_SOURCE_TYPE = "TrunkIo"
TRUNK_IO_API_VERSION_V2 = "v2"
FAILING_TESTS = "FailingTests"


def reset_v2_failing_tests(apps, schema_editor):
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # The effective pin is the schema's own, else the source's, else the source's default (v2).
    on_v2 = Q(api_version=TRUNK_IO_API_VERSION_V2) | (
        (Q(api_version__isnull=True) | Q(api_version=""))
        & (
            Q(source__api_version=TRUNK_IO_API_VERSION_V2)
            | Q(source__api_version__isnull=True)
            | Q(source__api_version="")
        )
    )
    schemas = ExternalDataSchema.objects.filter(
        on_v2, source__source_type=TRUNKIO_SOURCE_TYPE, name=FAILING_TESTS, deleted=False
    ).iterator()

    for schema in schemas:
        config = schema.sync_type_config or {}
        config["reset_pipeline"] = True
        schema.sync_type_config = config
        schema.save(update_fields=["sync_type_config"])


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0187_repin_teamtailor_api_version"),
    ]

    operations = [
        # Reverse is a no-op: the reset consumes itself on the next sync, and the v1 rows it wiped
        # cannot come back.
        migrations.RunPython(reset_v2_failing_tests, migrations.RunPython.noop, elidable=True),
    ]
