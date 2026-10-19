from django.db import migrations

# Whop sources were created before the source declared versions, so every row carries the
# unversioned "v1" label and the source sent no `Api-Version-Date` header. Whop then answered with
# the version pinned to each customer's API key, which is "2025-01-01" for older keys and the latest
# version for newer ones. The source now sends the pinned version as the header, and new sources
# default to the latest version. This pins every existing source to "2025-01-01", the contract the
# source was written against, so each one keeps the request and response shapes it already syncs.
#
# NULL pins are included because they resolve to the new default, which would silently move those
# sources to the latest version.
WHOP_SOURCE_TYPE = "Whop"
UNVERSIONED_API_VERSION = "v1"
WHOP_API_VERSION_2025_01_01 = "2025-01-01"


def pin_whop_sources_to_2025_01_01(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are
    # user-managed and stay as they are. Matching only the unversioned and NULL pins keeps this
    # idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=WHOP_SOURCE_TYPE, api_version=UNVERSIONED_API_VERSION).update(
        api_version=WHOP_API_VERSION_2025_01_01
    )
    ExternalDataSource.objects.filter(source_type=WHOP_SOURCE_TYPE, api_version__isnull=True).update(
        api_version=WHOP_API_VERSION_2025_01_01
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0185_externaldatadestination_health")]

    operations = [
        # Reverse is a no-op: pinned rows are indistinguishable from sources created on
        # "2025-01-01", so a blanket downgrade would clobber legitimate pins.
        migrations.RunPython(pin_whop_sources_to_2025_01_01, migrations.RunPython.noop, elidable=True),
    ]
