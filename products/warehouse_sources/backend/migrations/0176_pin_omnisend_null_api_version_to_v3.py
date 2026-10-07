from django.db import migrations

# Omnisend now defaults to 2026-03-15. That version moves to the `/api` base path with different
# auth, cursor pagination, renamed primary keys (contactID/campaignID/productID become `id`), prices
# in currency units instead of cents, and no list endpoints for carts or orders. Moving a source from
# v3 is lossy, and Omnisend has published no v3 sunset date, so v3 pins are intentionally NOT
# repinned here.
#
# This migration only backs out the NULL cohort from the default flip. A NULL `api_version` resolves
# to `default_version`, so an Omnisend source created without an explicit pin (direct-ORM/seeder paths
# that bypass the API's create-time stamping) would silently jump onto 2026-03-15. Pinning those rows
# to v3 keeps them on the version they were syncing.
OMNISEND_SOURCE_TYPE = "Omnisend"
OMNISEND_V3 = "v3"


def pin_null_omnisend_rows_to_v3(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pins only. Filtering on NULL keeps this idempotent and never overwrites an explicit
    # pin. Schema-level overrides (`ExternalDataSchema.api_version`) are customer-managed and untouched.
    ExternalDataSource.objects.filter(source_type=OMNISEND_SOURCE_TYPE, api_version__isnull=True).update(
        api_version=OMNISEND_V3
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0175_repin_llama_cloud_api_version")]

    operations = [
        # Reverse is a no-op: once pinned, a v3 row is indistinguishable from one natively stamped v3,
        # so re-nulling would wrongly clear legitimate explicit pins too.
        migrations.RunPython(pin_null_omnisend_rows_to_v3, migrations.RunPython.noop, elidable=False),
    ]
