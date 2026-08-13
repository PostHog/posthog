from django.db import migrations

# Lightspeed Retail (X-Series) deprecated the legacy 2.0 version; deprecated endpoints increasingly
# return 410 Gone before an eventual retirement. Repin source-level pins onto the current 2026-01
# date-based version. The endpoints/fields this source reads carry no documented breaking changes
# across the two versions (it auto-infers its schema and reads the same `version` keyset cursor), so
# the repin needs no data/schema transform — only the pin moves.
LIGHTSPEED_RETAIL_SOURCE_TYPE = "LightspeedRetail"
DEPRECATED_VERSION = "2.0"
TARGET_VERSION = "2026-01"


def repin_lightspeed_retail_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated version. NULL pins already resolve to the
    # source's `default_version` (now 2026-01), so they need no update. Filtering on the exact old
    # value keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (`ExternalDataSchema.api_version`) are intentionally customer-pinned and are left untouched.
    ExternalDataSource.objects.filter(source_type=LIGHTSPEED_RETAIL_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0091_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate 2026-01 pins.
        migrations.RunPython(repin_lightspeed_retail_api_version, migrations.RunPython.noop, elidable=False),
    ]
