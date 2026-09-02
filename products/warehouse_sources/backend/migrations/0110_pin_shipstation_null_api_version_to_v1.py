from django.db import migrations

# ShipStation's default vendor API version flips to "v2" (the ShipEngine-based API) in the same
# change that adds this migration. Existing ShipStation rows were pinned "v1" by migration 0075, but
# a row created via a direct-ORM path that bypasses creation-time stamping could still have a NULL
# `api_version`, and a NULL pin resolves to `default_version` — so it would silently follow the flip
# to v2. v2 needs a different credential (a single API-Key the customer must generate) and exposes a
# different table set, so an unpinned v1 source moved to v2 would break. Pin any such rows back to
# "v1" so the flip only affects newly created sources.
#
# This does NOT repin v1 customers to v2: that migration is not safe to script (v2 credentials can't
# be derived from v1's, and the resource set differs), so it is documented as a manual path in the PR.
SHIPSTATION_SOURCE_TYPE = "ShipStation"
SHIPSTATION_V1 = "v1"


def pin_null_shipstation_rows_to_v1(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # The isnull guard keeps it idempotent (safe under retries) and never overwrites a concrete pin.
    ExternalDataSource.objects.filter(source_type=SHIPSTATION_SOURCE_TYPE, api_version__isnull=True).update(
        api_version=SHIPSTATION_V1
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0109_repin_ably_api_version_v2"),
    ]

    operations = [
        # Reverse is a no-op: after this runs, the pinned rows are indistinguishable from natively
        # created v1 sources, so nulling "v1" pins would also destroy legitimate creation-time stamps.
        migrations.RunPython(pin_null_shipstation_rows_to_v1, migrations.RunPython.noop, elidable=True),
    ]
