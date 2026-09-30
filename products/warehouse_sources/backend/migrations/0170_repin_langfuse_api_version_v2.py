from django.db import migrations

# The Langfuse source defaults new instances to v2 and marks v1 as deprecated. The v1 and v2 labels
# send identical requests, so this repins existing source-level pins from v1 to v2. Only the label
# changes, and the in-product deprecation warning clears.
LANGFUSE_SOURCE_TYPE = "Langfuse"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_langfuse_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides
    # are user-managed and are left alone.
    #
    # NULL pins already resolve to the source's `default_version` (v2), so they need no update.
    # Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=LANGFUSE_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0169_warehousecolumnstatistics_full_scan_at")]

    operations = [
        # Reverse is a no-op: repinned rows are indistinguishable from natively-created v2 rows, so a
        # blanket downgrade would clobber legitimate v2 pins.
        migrations.RunPython(repin_langfuse_v1_to_v2, migrations.RunPython.noop, elidable=False),
    ]
