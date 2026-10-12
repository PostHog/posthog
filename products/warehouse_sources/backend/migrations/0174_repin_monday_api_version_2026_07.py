from django.db import migrations

# monday.com deprecated API version 2024-10 (the framework "v2" label) on 2026-02-15. monday does not
# reject the retired header: it answers with its maintenance version, so a "v2" pin silently stops
# selecting the version it names. Every query this source sends is valid under 2026-07, and every
# table is full refresh, so the repin needs no data or schema transform.
# This moves the source-level pin only; schema-level `ExternalDataSchema.api_version` overrides are
# user-managed and intentionally left untouched. NULL pins already resolve to the new default.
SOURCE_TYPE = "Monday"
DEPRECATED_VERSION = "v2"
NEW_VERSION = "2026-07"


def repin_monday_to_2026_07(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # One row per configured source, so a single bulk update is quick. Idempotent: a second run finds
    # no v2 monday.com rows.
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0173_repair_legacy_full_sync_type")]

    operations = [
        # Reverse is a no-op: once repinned, 2026-07 rows are indistinguishable from natively-created ones,
        # so a blanket downgrade would clobber legitimate 2026-07 pins made after this ran.
        migrations.RunPython(repin_monday_to_2026_07, migrations.RunPython.noop, elidable=True),
    ]
