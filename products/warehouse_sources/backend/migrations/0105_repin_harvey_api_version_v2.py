from django.db import migrations

# Harvey retired its v1 Usage and Query History APIs on 2025-06-30 in favor of the v2 event-based
# schema. The source now defaults new instances to v2; this repins existing source-level pins from
# v1 to v2 so their stored version matches the wire the source already talks to and the in-product
# deprecation warning clears.
HARVEY_SOURCE_TYPE = "Harvey"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_harvey_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides
    # are user-managed (a customer intentionally pinned that schema) and are left alone — the
    # schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (now v2), so they need no update.
    # Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=HARVEY_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0104_easybill_source"),
    ]

    operations = [
        # Reverse is a no-op: nulling or downgrading pins would move customers back onto the
        # retired v1 label and clobber any deliberate post-migration pins.
        migrations.RunPython(repin_harvey_v1_to_v2, migrations.RunPython.noop, elidable=False),
    ]
