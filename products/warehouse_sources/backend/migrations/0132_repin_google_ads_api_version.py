from django.db import migrations

# Google is sunsetting the Google Ads API v23 (scheduled February 2027) in favor of v25, the current
# default. This repins the source-level pin only, and only for rows explicitly on v23: NULL pins
# already resolve to the v25 default (the default is not flipped here), and v24 pins stay on v24 —
# Google still serves v24, so moving them is a separate, later decision. The request layer already
# supports v23/v24/v25; on the next sync a repinned source rediscovers its schemas under v25 via the
# version-aware discovery path, and merge-by-primary-key keeps that idempotent, so no data transform
# is scripted here. Schema-level `ExternalDataSchema.api_version` overrides are user-managed by design
# and intentionally left untouched — the schema-level deprecation banner prompts those migrations.
SOURCE_TYPE = "GoogleAds"
DEPRECATED_VERSION = "v23"
NEW_VERSION = "v25"


def repin_google_ads_to_v25(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # ExternalDataSource is one row per configured source (thousands, not events-scale), so a single
    # bulk update in the migration's transaction is quick. Idempotent: a second run finds no v23 rows.
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0131_pin_leadfeeder_null_api_version_to_v1")]

    operations = [
        # Reverse is a no-op: once repinned, v25 rows are indistinguishable from natively-created ones,
        # so a blanket downgrade would clobber legitimate v25 pins made after this ran.
        migrations.RunPython(repin_google_ads_to_v25, migrations.RunPython.noop, elidable=True),
    ]
