from django.db import migrations

# Google Ads is retiring v24 on its rolling ~12-month schedule (v25 is the current major). Repin
# source-level pins from v24 onto v25. This source reads the same resources and fields under both
# versions — v25's breaking changes only remove the lifecycle-goal resources it never touches — so
# the repin needs no data/schema transform; only the pin moves.
GOOGLE_ADS_SOURCE_TYPE = "GoogleAds"
DEPRECATED_VERSION = "v24"
TARGET_VERSION = "v25"


def repin_google_ads_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated version. NULL pins already resolve to the
    # source's `default_version` (now v25), so they need no update. Filtering on the exact old value
    # keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (`ExternalDataSchema.api_version`) are intentionally customer-pinned and are left untouched.
    ExternalDataSource.objects.filter(source_type=GOOGLE_ADS_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0104_easybill_source"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, a source on v25 is indistinguishable from one natively
        # created on the new default, so a blanket downgrade would clobber legitimate native pins.
        migrations.RunPython(repin_google_ads_api_version, migrations.RunPython.noop, elidable=False),
    ]
