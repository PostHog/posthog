from django.db import migrations

# Meta's Graph API v25.0 entered its deprecated phase and the vendor sunsets it on 2028-07-29.
# Repin source-level pins onto v26.0. Both versions differ only in the URL version segment the
# source sends; the endpoints, fields, and response shapes this source reads are identical across
# them, so the repin needs no data/schema transform — only the pin moves.
META_ADS_SOURCE_TYPE = "MetaAds"
DEPRECATED_VERSION = "v25.0"
TARGET_VERSION = "v26.0"


def repin_meta_ads_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated version. NULL pins already resolve to the
    # source's `default_version` (v26.0), so they need no update. Filtering on the exact old value
    # keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (`ExternalDataSchema.api_version`) are intentionally customer-pinned and are left untouched.
    ExternalDataSource.objects.filter(source_type=META_ADS_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0152_callable_choices"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, a source on v26.0 is indistinguishable from one
        # natively created on the new default, so downgrading every v26.0 row would clobber
        # legitimate native pins.
        migrations.RunPython(repin_meta_ads_api_version, migrations.RunPython.noop, elidable=True),
    ]
