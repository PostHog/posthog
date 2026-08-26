from django.db import migrations

# GitHub is deprecating the 2022-11-28 REST API version (its X-GitHub-Api-Version header value),
# which returns 410 Gone at least 24 months after the 2026-03-10 release. This repins existing
# source-level pins from "2022-11-28" to "2026-03-10" (the current default) so they stop sending a
# header GitHub will stop accepting. The response shapes GitHub serves for the endpoints this source
# reads are unchanged across the two versions, so only the pin moves — no data/schema transform.
SOURCE_TYPE = "Github"
DEPRECATED_VERSION = "2022-11-28"
NEW_VERSION = "2026-03-10"


def repin_github_2022_to_2026(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are user-managed
    # (a customer intentionally pinned that schema) and are left alone — the schema-level deprecation
    # banner prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (already "2026-03-10"), so they need
    # no update. Matching only `api_version="2022-11-28"` keeps this idempotent: a second run matches
    # nothing. ExternalDataSource is one row per configured source, so a single bulk update is quick.
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0154_repin_mem0_api_version")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate "2026-03-10" pins and move customers
        # back onto the sunset header.
        migrations.RunPython(repin_github_2022_to_2026, migrations.RunPython.noop, elidable=True),
    ]
