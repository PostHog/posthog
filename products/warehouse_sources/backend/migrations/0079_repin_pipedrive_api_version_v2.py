from django.db import migrations

# Pipedrive deprecated the v1 API endpoints that have v2 replacements (sunset 2025-12-31). The
# source now defaults new instances to v2; this repins existing source-level pins from v1 to v2
# so they stop using the deprecated `/api/v1/activities` endpoint.
PIPEDRIVE_SOURCE_TYPE = "Pipedrive"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_pipedrive_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version`
    # overrides are user-managed (a customer intentionally pinned that schema) and are left
    # alone — the schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (now v2), so they need no
    # update. Matching only `api_version="v1"` keeps this idempotent: a second run matches
    # nothing, and any row a customer re-pins to v1 after this ran would (intentionally) be
    # repinned again only if the migration is re-applied — acceptable, since v1 is deprecated.
    ExternalDataSource.objects.filter(source_type=PIPEDRIVE_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0078_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        # Reverse is a no-op: nulling or downgrading pins would move customers back onto the
        # deprecated version and clobber any deliberate post-migration pins.
        migrations.RunPython(repin_pipedrive_v1_to_v2, migrations.RunPython.noop, elidable=False),
    ]
