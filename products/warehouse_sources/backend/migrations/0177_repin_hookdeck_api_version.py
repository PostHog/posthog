from django.db import migrations

# Hookdeck supports each dated API version for one year after its release, so "2025-07-01" stopped
# being officially supported on 2026-07-01. This repins source-level pins from "2025-07-01" to
# "2026-09-01" (the current default).
#
# No data or schema transform accompanies the repin. The only difference between the versions is
# that a destination's `config.rate_limit` / `config.rate_limit_period` move to
# `config.delivery_policy.rate` / `.period`. That shape reaches only the `destinations` and
# `connections` tables, both full refresh, so the next scheduled sync drops each table and
# rebuilds it in the new shape.
HOOKDECK_SOURCE_TYPE = "Hookdeck"
HOOKDECK_API_VERSION_2025_07_01 = "2025-07-01"
HOOKDECK_API_VERSION_2026_09_01 = "2026-09-01"


def repin_hookdeck_2025_07_01_to_2026_09_01(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are user-managed
    # (a customer intentionally pinned that schema) and are left alone. The schema-level deprecation
    # warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the default ("2026-09-01"), so they need no update. Matching only
    # `api_version="2025-07-01"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(
        source_type=HOOKDECK_SOURCE_TYPE, api_version=HOOKDECK_API_VERSION_2025_07_01
    ).update(api_version=HOOKDECK_API_VERSION_2026_09_01)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0176_repin_lightspeed_retail_api_version_2026_07"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, "2026-09-01" rows are indistinguishable from
        # natively-created ones, so a blanket downgrade would clobber legitimate "2026-09-01" pins.
        migrations.RunPython(repin_hookdeck_2025_07_01_to_2026_09_01, migrations.RunPython.noop, elidable=True),
    ]
