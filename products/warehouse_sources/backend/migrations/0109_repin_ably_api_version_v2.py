from django.db import migrations

# Ably sunset REST protocol v1 on 2025-11-01; the source now defaults new instances to "2" and
# sends `X-Ably-Version: 2` explicitly. This repins existing source-level pins from the legacy
# unversioned label ("v1") to "2" so they stop tracking Ably's mutable default and stay on
# protocol 2. The `/stats` endpoint and its response shape are identical across the two protocol
# versions and the source auto-infers its schema, so no data/schema transform is needed — only
# the pin moves.
ABLY_SOURCE_TYPE = "Ably"
OLD_VERSION = "v1"
NEW_VERSION = "2"


def repin_ably_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version`
    # overrides are user-managed (a customer intentionally pinned that schema) and are left
    # alone — the schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (now "2"), so they need no
    # update. Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=ABLY_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0108_pin_zendesk_sunshine_v1")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate "2" pins and move customers back
        # onto the sunset v1 protocol.
        migrations.RunPython(repin_ably_v1_to_v2, migrations.RunPython.noop, elidable=False),
    ]
