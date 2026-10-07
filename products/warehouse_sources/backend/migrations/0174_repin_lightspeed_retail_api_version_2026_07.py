from django.db import migrations

# Lightspeed Retail (X-Series) supports the 2026-01 version until January 2027. After that a request
# to it is served by the oldest supported version instead of failing, so the pin silently stops being
# honored. Repin source-level pins onto 2026-07 (the current default). For the endpoints this source
# reads, 2026-04 and 2026-07 only add fields (inventory reorder fields), which the auto-inferred
# schema picks up, so only the pin moves. No data/schema transform is needed.
LIGHTSPEED_RETAIL_SOURCE_TYPE = "LightspeedRetail"
DEPRECATED_VERSION = "2026-01"
TARGET_VERSION = "2026-07"


def repin_lightspeed_retail_api_version_2026_07(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated version. NULL pins already resolve to the
    # source's `default_version` (2026-07), and pins on the separately deprecated 2.0 stay put.
    # Filtering on the exact old value keeps this idempotent: a re-run matches nothing. Schema-level
    # overrides (`ExternalDataSchema.api_version`) are customer-pinned and are left untouched.
    ExternalDataSource.objects.filter(source_type=LIGHTSPEED_RETAIL_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0173_repair_legacy_full_sync_type"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate 2026-07 pins.
        migrations.RunPython(repin_lightspeed_retail_api_version_2026_07, migrations.RunPython.noop, elidable=True),
    ]
