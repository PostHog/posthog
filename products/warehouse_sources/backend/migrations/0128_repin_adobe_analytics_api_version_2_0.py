from django.db import migrations

# Adobe deprecated its legacy 1.4 API (the framework "v1" label) with a vendor sunset of 2026-08-12
# in favor of the 2.0 REST API. This source's client has only ever spoken 2.0, so a v1 pin and a 2.0
# pin hit the exact same wire — repinning is a lossless label change with no data or schema transform.
# This moves the source-level pin only; schema-level `ExternalDataSchema.api_version` overrides are
# user-managed and intentionally left untouched.
SOURCE_TYPE = "AdobeAnalytics"
DEPRECATED_VERSION = "v1"
NEW_VERSION = "2.0"


def repin_adobe_analytics_to_2_0(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # ExternalDataSource is one row per configured source (thousands, not events-scale), so a single
    # bulk update in the migration's transaction is quick. Idempotent: a second run finds no v1/NULL
    # Adobe Analytics rows. NULL pins are repinned too — they otherwise silently follow the flipped
    # default_version to 2.0, so pinning them makes the migration explicit and reviewable.
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=NEW_VERSION
    )
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version__isnull=True).update(api_version=NEW_VERSION)


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0127_pin_qualys_vmdr_null_api_version_to_2_0")]

    operations = [
        # Reverse is a no-op: once repinned, 2.0 rows are indistinguishable from natively-created ones,
        # so a blanket downgrade would clobber legitimate 2.0 pins made after this ran.
        migrations.RunPython(repin_adobe_analytics_to_2_0, migrations.RunPython.noop, elidable=True),
    ]
