from django.db import migrations

# Gusto's final sunset for API version "2024-04-01" was 2026-06-15, and every call pinned to it now
# returns 406. This repins source-level pins from "2024-04-01" to "2026-06-15" (the current default).
#
# No data or schema transform accompanies the repin. Both versions call the same `/v1` paths with
# the same `page`/`per` pagination, and only the `X-Gusto-API-Version` header differs. The changes
# between them that touch columns this source reads do not need a transform. Gusto renamed
# `auto_pilot` to `auto_payroll` and changed nested `employee_compensations` amounts from numbers to
# strings. A renamed column appears as a new column, and nested values land in a JSON column, so
# no merge-based table gets a column type it cannot widen. `pay_schedules` is full refresh and
# rebuilds on its next sync.
GUSTO_SOURCE_TYPE = "Gusto"
GUSTO_API_VERSION_2024_04_01 = "2024-04-01"
GUSTO_API_VERSION_2026_06_15 = "2026-06-15"


def repin_gusto_2024_04_01_to_2026_06_15(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are user-managed
    # (a customer intentionally pinned that schema) and are left alone. The schema-level deprecation
    # warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` ("2026-06-15"), so they need no
    # update. Matching only `api_version="2024-04-01"` keeps this idempotent: a second run matches
    # nothing. ExternalDataSource is one row per configured source, so a single bulk update is quick.
    ExternalDataSource.objects.filter(source_type=GUSTO_SOURCE_TYPE, api_version=GUSTO_API_VERSION_2024_04_01).update(
        api_version=GUSTO_API_VERSION_2026_06_15
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0178_pin_unpinned_buildbetter_sources_to_v1"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, "2026-06-15" rows are indistinguishable from
        # natively-created ones, so a blanket downgrade would clobber legitimate "2026-06-15" pins
        # and move customers back onto the sunset version.
        migrations.RunPython(repin_gusto_2024_04_01_to_2026_06_15, migrations.RunPython.noop, elidable=True),
    ]
