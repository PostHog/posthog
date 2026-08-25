from django.db import migrations

# OwnerRez has deprecated its v1.x API in favor of v2.0. This source's client has only ever built
# /v2 paths, so a "v1" pin (the framework's legacy unversioned label) and a "v2.0" pin hit the exact
# same wire — repinning is a lossless label change with no data or schema transform.
# This moves the source-level pin only; schema-level `ExternalDataSchema.api_version` overrides are
# user-managed and intentionally left untouched.
SOURCE_TYPE = "Ownerrez"
DEPRECATED_VERSION = "v1"
NEW_VERSION = "v2.0"


def repin_ownerrez_to_v2_0(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # ExternalDataSource is one row per configured source (thousands, not events-scale), so a single
    # bulk update in the migration's transaction is quick. Idempotent: a second run finds no v1/NULL
    # OwnerRez rows. NULL pins are repinned too — they otherwise silently follow the flipped
    # default_version to v2.0, so pinning them makes the migration explicit and reviewable.
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=NEW_VERSION
    )
    ExternalDataSource.objects.filter(source_type=SOURCE_TYPE, api_version__isnull=True).update(api_version=NEW_VERSION)


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0155_repin_github_api_version")]

    operations = [
        # Reverse is a no-op: once repinned, v2.0 rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate v2.0 pins made after this ran.
        migrations.RunPython(repin_ownerrez_to_v2_0, migrations.RunPython.noop, elidable=True),
    ]
