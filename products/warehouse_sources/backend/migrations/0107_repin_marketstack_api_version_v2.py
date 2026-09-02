from django.db import migrations

# Marketstack deprecated its v1 API (vendor sunset 2025-06-30) in favor of v2. v2 is a compatible
# additive superset for every table we sync — same auth, pagination, response/error envelope, and
# primary keys; only new response columns, which the auto-inferred schema absorbs — so repinning is
# lossless and needs no data/schema transform. This moves the source-level pin only; schema-level
# `ExternalDataSchema.api_version` overrides are user-managed and intentionally left untouched.
SOURCE_TYPE = "Marketstack"
DEPRECATED_VERSION = "v1"
NEW_VERSION = "v2"


def repin_marketstack_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # ExternalDataSource is one row per configured source (thousands, not events-scale), so a single
    # bulk update in the migration's transaction is quick. Idempotent: a second run finds no v1/NULL
    # Marketstack rows. NULL pins are repinned too — they otherwise silently follow the flipped
    # default_version to v2, so pinning them makes the migration to v2 explicit and reviewable.
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=NEW_VERSION
    )
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version__isnull=True).update(api_version=NEW_VERSION)


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0106_repin_clockodo_api_version")]

    operations = [
        # Reverse is a no-op: once repinned, v2 rows are indistinguishable from natively-created ones,
        # so a blanket downgrade would clobber legitimate v2 pins made after this ran.
        migrations.RunPython(repin_marketstack_to_v2, migrations.RunPython.noop, elidable=True),
    ]
