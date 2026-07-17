from django.db import migrations

# Klaviyo's 2024-10-15 revision entered its deprecated phase and retires ~2026-10-15 (falling
# forward / returning 410 thereafter). Repin source-level pins onto the current 2026-07-15 revision.
# The endpoints/fields this source reads are backward compatible across the two revisions, so the
# repin needs no data/schema transform — only the pin moves.
KLAVIYO_SOURCE_TYPE = "Klaviyo"
DEPRECATED_VERSION = "2024-10-15"
TARGET_VERSION = "2026-07-15"


def repin_klaviyo_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated revision. NULL pins already resolve to the
    # source's `default_version` (now 2026-07-15), so they need no update. Filtering on the exact old
    # value keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (`ExternalDataSchema.api_version`) are intentionally customer-pinned and are left untouched.
    ExternalDataSource.objects.filter(source_type=KLAVIYO_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0078_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, a source on 2026-07-15 is indistinguishable from one
        # natively created on the new default, so downgrading every 2026-07-15 row would clobber
        # legitimate native pins.
        migrations.RunPython(repin_klaviyo_api_version, migrations.RunPython.noop, elidable=True),
    ]
