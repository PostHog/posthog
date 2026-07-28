from django.db import migrations

# EmailOctopus has deprecated its v1 vendor API (no announced sunset date). The source now defaults
# new instances to v2; this repins existing source-level pins from v1 to v2. Both labels resolve to
# the same REST host today (the version isn't carried in EmailOctopus requests), so this is a plain
# pin update with no data/schema transform — it just moves rows off the deprecated label.
EMAILOCTOPUS_SOURCE_TYPE = "EmailOctopus"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_emailoctopus_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version`
    # overrides are user-managed (a customer intentionally pinned that schema) and are left
    # alone — the schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (now v2), so they need no
    # update. Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=EMAILOCTOPUS_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0104_easybill_source"),
    ]

    operations = [
        # Reverse is a no-op: nulling or downgrading pins would move customers back onto the
        # deprecated version and clobber any deliberate post-migration pins.
        migrations.RunPython(repin_emailoctopus_v1_to_v2, migrations.RunPython.noop, elidable=False),
    ]
