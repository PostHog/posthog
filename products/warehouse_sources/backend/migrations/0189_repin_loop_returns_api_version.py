from django.db import migrations

# Loop removes the `v1` alias when the `2026-07` version it points at sunsets on 2028-07-15. After the
# sunset Loop does not reject the request: it serves the oldest supported version, so a `v1` pin silently
# stops selecting the version it names. This repins source-level `v1` pins to "2026-10" (the current
# default).
#
# No data or schema transform accompanies the repin. Both versions call the same list paths with the same
# pagination and response shapes; only the version segment in the URL differs. The 2026-10 breaking changes
# touch write endpoints, draft returns and a 120-day range check on the ASN report, which this source
# already stays under with 90-day windows.
SOURCE_TYPE = "LoopReturns"
DEPRECATED_VERSION = "v1"
NEW_VERSION = "2026-10"


def repin_loop_returns_v1_to_2026_10(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are user-managed (a
    # customer intentionally pinned that schema) and are left alone. The schema-level deprecation warning
    # prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` ("2026-10"), and "2026-07" pins are still
    # served, so neither is touched. Matching only `api_version="v1"` keeps this idempotent: a second run
    # matches nothing.
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0188_reset_trunkio_v2_failing_tests"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, "2026-10" rows are indistinguishable from natively-created ones,
        # so a blanket downgrade would clobber legitimate "2026-10" pins.
        migrations.RunPython(repin_loop_returns_v1_to_2026_10, migrations.RunPython.noop, elidable=True),
    ]
