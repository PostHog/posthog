from django.db import migrations

# Meta's Graph API v22.0 is deprecated and the vendor stops serving it on 2027-05-20. Meta does not
# reject a call on a retired version; it upgrades the call to the oldest version still served, so a
# pin left behind moves silently instead of failing. Repin source-level pins onto v26.0 (the current
# default). The versions differ only in the URL version segment the source sends: the edges, fields,
# pagination, and response handling this source uses are identical across them, so the repin needs
# no data/schema transform — only the pin moves.
INSTAGRAM_SOURCE_TYPE = "Instagram"
DEPRECATED_VERSION = "v22.0"
TARGET_VERSION = "v26.0"


def repin_instagram_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated version. NULL pins already resolve to the
    # source's `default_version` (v26.0), and v23.0 pins are still served, so both stay put. Filtering
    # on the exact old value keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (`ExternalDataSchema.api_version`) are intentionally customer-pinned and are left untouched.
    ExternalDataSource.objects.filter(source_type=INSTAGRAM_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0177_repin_hookdeck_api_version"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, a source on v26.0 is indistinguishable from one
        # natively created on the new default, so downgrading every v26.0 row would clobber
        # legitimate native pins.
        migrations.RunPython(repin_instagram_api_version, migrations.RunPython.noop, elidable=True),
    ]
