from django.db import migrations

# LinkedIn sunsets each versioned API header a minimum of one year after release. The legacy
# unversioned label ("v1") sends the header the source has always sent (202508, August 2025),
# which reached that one-year mark and now gets a 426 NONEXISTENT_VERSION on every call. This
# repins existing source-level pins from "v1" to "202607" (the current default) so they stop
# sending a header LinkedIn no longer accepts. The request/response shape LinkedIn serves under
# 202607 for the tables this source reads is unchanged from what "v1" (202508) served, so no
# data/schema transform is needed — only the pin moves.
LINKEDIN_ADS_SOURCE_TYPE = "LinkedinAds"
OLD_VERSION = "v1"
NEW_VERSION = "202607"


def repin_linkedin_ads_v1_to_202607(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version`
    # overrides are user-managed (a customer intentionally pinned that schema) and are left
    # alone — the schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (already "202607"), so they
    # need no update. Matching only `api_version="v1"` keeps this idempotent: a second run
    # matches nothing.
    ExternalDataSource.objects.filter(source_type=LINKEDIN_ADS_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0138_scaffold_wisprflow_source")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate "202607" pins and move customers back
        # onto the sunset v1 header.
        migrations.RunPython(repin_linkedin_ads_v1_to_202607, migrations.RunPython.noop, elidable=False),
    ]
