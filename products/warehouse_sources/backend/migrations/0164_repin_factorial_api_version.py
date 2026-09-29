from django.db import migrations

# Factorial serves each quarterly version for one year, so "2025-04-01" stopped being served on
# 2026-04-01. A request on a retired version is not rejected — Factorial serves it "using the oldest
# version schema" instead — so a pin left behind moves silently rather than failing loudly, which is
# exactly what the pinning framework exists to prevent. This repins source-level pins from
# "2025-04-01" to "2026-07-01" (the current default).
#
# No data or schema transform accompanies the repin. The versions differ only in that "2026-07-01"
# serializes resource ids as opaque strings: the paths, the pagination cursor, and the response
# envelope are unchanged, the primary key stays the auto-inferred `id` column, and every Factorial
# schema is full refresh, so the next scheduled sync drops the table and rebuilds it under the new
# inferred types.
FACTORIAL_SOURCE_TYPE = "Factorial"
FACTORIAL_API_VERSION_2025_04_01 = "2025-04-01"
FACTORIAL_API_VERSION_2026_07_01 = "2026-07-01"


def repin_factorial_2025_04_01_to_2026_07_01(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are user-managed
    # (a customer intentionally pinned that schema) and are left alone — the schema-level deprecation
    # warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` ("2026-07-01"), so they need no
    # update, and "2026-04-01" pins are still served by Factorial and stay put. Matching only
    # `api_version="2025-04-01"` keeps this idempotent: a second run matches nothing.
    # ExternalDataSource is one row per configured source, so a single bulk update is quick.
    ExternalDataSource.objects.filter(
        source_type=FACTORIAL_SOURCE_TYPE, api_version=FACTORIAL_API_VERSION_2025_04_01
    ).update(api_version=FACTORIAL_API_VERSION_2026_07_01)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0163_externaldataschema_auto_disabled_at"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, "2026-07-01" rows are indistinguishable from
        # natively-created ones, so a blanket downgrade would clobber legitimate "2026-07-01" pins
        # and move customers back onto the sunset version.
        migrations.RunPython(repin_factorial_2025_04_01_to_2026_07_01, migrations.RunPython.noop, elidable=True),
    ]
