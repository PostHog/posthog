from django.db import migrations

# Mem0 dropped the legacy v1 API generation in its 2.0.0 SDK release, so "v1" is now deprecated.
# For the tables this source reads, our "v1" label and the "v3" default resolve to byte-identical
# requests (memories on /v3/, entities and events on /v1/ — no version header, no per-version
# dispatch), so this repin is a pure relabel: it moves existing source-level pins from "v1" to "v3"
# without changing a single byte on the wire. No data or schema transform is needed.
MEM0_SOURCE_TYPE = "Mem0"
OLD_VERSION = "v1"
NEW_VERSION = "v3"


def repin_mem0_v1_to_v3(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides
    # are user-managed (a customer intentionally pinned that schema) and are left alone — the
    # schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` ("v3"), so they need no update.
    # Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=MEM0_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0153_repin_meta_ads_api_version")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate "v3" pins.
        migrations.RunPython(repin_mem0_v1_to_v3, migrations.RunPython.noop, elidable=False),
    ]
