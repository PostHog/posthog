from django.db import migrations

# incident.io removes GET /v2/follow_ups on 2026-12-31, which the "v1" label reads for the
# follow_ups table; its successor is GET /v3/follow_ups. The source now defaults new instances to
# "v3", which reads that successor and keeps every other table on the same path as "v1". This
# repins existing source-level pins from "v1" to "v3" so their next sync reads the live endpoint.
# follow_ups is full refresh only and keeps the string `id` primary key, so the next sync rebuilds
# the table with the new `category` column; the pin is the only thing that needs to move.
INCIDENT_IO_SOURCE_TYPE = "IncidentIo"
OLD_VERSION = "v1"
NEW_VERSION = "v3"


def repin_incident_io_v1_to_v3(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only source-level pins still on the deprecated version move. NULL pins already resolve to
    # the source's default_version (now "v3"), so they need no update. Filtering on the exact old
    # value keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (ExternalDataSchema.api_version) are intentionally customer-pinned and are left untouched;
    # the schema-level deprecation warning prompts the user to migrate those.
    ExternalDataSource.objects.filter(source_type=INCIDENT_IO_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0176_repin_lightspeed_retail_api_version_2026_07")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # v3 rows, so a blanket downgrade would clobber legitimate v3 pins and move customers back
        # onto an endpoint that stops being served after the sunset.
        migrations.RunPython(repin_incident_io_v1_to_v3, migrations.RunPython.noop, elidable=False),
    ]
