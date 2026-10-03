from django.db import migrations

# LinkedIn's 202606 monthly version is deprecated and sunsets 2027-06-15 (a 426 `NONEXISTENT_VERSION`
# thereafter). Repin source-level pins onto the current 202608 version. 202608's changes are additive
# for the endpoints/fields this source reads (ad accounts, campaigns, campaign groups, creatives,
# conversions, ad analytics), so the repin needs no data/schema transform — only the pin moves.
LINKEDIN_ADS_SOURCE_TYPE = "LinkedinAds"
DEPRECATED_VERSION = "202606"
TARGET_VERSION = "202608"


def repin_linkedin_ads_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated version. NULL pins already resolve to the
    # source's `default_version` (now 202608), so they need no update. Filtering on the exact old value
    # keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (`ExternalDataSchema.api_version`) are intentionally customer-pinned and are left untouched.
    ExternalDataSource.objects.filter(source_type=LINKEDIN_ADS_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0150_repin_bloomerang_api_version"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, a source on 202608 is indistinguishable from one natively
        # created on the new default, so downgrading every 202608 row would clobber legitimate native pins.
        migrations.RunPython(repin_linkedin_ads_api_version, migrations.RunPython.noop, elidable=True),
    ]
