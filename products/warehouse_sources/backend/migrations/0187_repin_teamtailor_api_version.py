from django.db import migrations

# Teamtailor's changelog entry of 2025-10-01 requires `X-Api-Version: 20240904` on every request, so
# "20240404" is no longer served. This repins source-level pins from "20240404" to "20240904" (the
# current default).
#
# No data or schema transform accompanies the repin. Both versions call the same `/v1` list paths
# with the same JSON:API cursor pagination, and only the `X-Api-Version` header differs. The one
# breaking change in "20240904" reshapes the notes listing, which this source does not read. Every
# Teamtailor table is full refresh, so each rebuilds on its next sync.
TEAMTAILOR_SOURCE_TYPE = "Teamtailor"
TEAMTAILOR_API_VERSION_20240404 = "20240404"
TEAMTAILOR_API_VERSION_20240904 = "20240904"


def repin_teamtailor_20240404_to_20240904(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are user-managed
    # (a customer intentionally pinned that schema) and are left alone. The schema-level deprecation
    # warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` ("20240904"), so they need no
    # update. Matching only `api_version="20240404"` keeps this idempotent: a second run matches
    # nothing.
    ExternalDataSource.objects.filter(
        source_type=TEAMTAILOR_SOURCE_TYPE, api_version=TEAMTAILOR_API_VERSION_20240404
    ).update(api_version=TEAMTAILOR_API_VERSION_20240904)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0186_pin_whop_api_version_2025_01_01"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, "20240904" rows are indistinguishable from
        # natively-created ones, so a blanket downgrade would clobber legitimate "20240904" pins
        # and move customers back onto the retired version.
        migrations.RunPython(repin_teamtailor_20240404_to_20240904, migrations.RunPython.noop, elidable=True),
    ]
