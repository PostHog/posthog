from django.db import migrations

# Clockodo decommissions the v2 endpoints behind six of this source's tables on 2026-05-01
# (customers, projects, services, lumpsum_services, users, teams), replacing them with
# individually-versioned v3/v4 successors; surcharges and entries stay on v2. The source now
# defaults new instances to "v3", whose endpoint map routes each table to its non-deprecated
# successor. This repins existing source-level pins from "v2" to "v3" so their next sync reads
# the live endpoints. Every Clockodo table is full refresh only and the successors keep the
# integer `id` primary key, so the next full-refresh sync auto-infers the v3/v4 columns; the pin
# is the only thing that needs to move.
CLOCKODO_SOURCE_TYPE = "Clockodo"
OLD_VERSION = "v2"
NEW_VERSION = "v3"


def repin_clockodo_v2_to_v3(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only source-level pins still on the deprecated version move. NULL pins already resolve to
    # the source's default_version (now "v3"), so they need no update. Filtering on the exact old
    # value keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (ExternalDataSchema.api_version) are intentionally customer-pinned and are left untouched;
    # the schema-level deprecation warning prompts the user to migrate those.
    ExternalDataSource.objects.filter(source_type=CLOCKODO_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0105_repin_harvey_api_version_v2")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # v3 rows, so a blanket downgrade would clobber legitimate v3 pins and move customers back
        # onto endpoints that 404 after the sunset.
        migrations.RunPython(repin_clockodo_v2_to_v3, migrations.RunPython.noop, elidable=False),
    ]
