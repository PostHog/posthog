from django.db import migrations

# Leadfeeder's default vendor API version flips to "2026-08-07" (the unified Dealfront API) in the
# same change that adds this migration. Existing Leadfeeder rows were pinned "v1" by migration 0075,
# but a row created via a direct-ORM path that bypasses creation-time stamping could still have a
# NULL `api_version`, and a NULL pin resolves to `default_version` — so it would silently follow the
# flip to the unified API. The unified API needs a different credential (an X-Api-Key generated in
# the Dealfront platform, which cannot be derived from a legacy Token) and a different request layer,
# so an unpinned legacy source moved to it would break. Pin any such rows back to "v1" so the flip
# only affects newly created sources.
#
# This does NOT repin legacy "v1" customers to the unified API: that migration is not safe to script
# (the unified credential can't be derived from the legacy one, and the deprecation carries no sunset
# date), so it is documented as a manual path in the PR.
LEADFEEDER_SOURCE_TYPE = "Leadfeeder"
LEADFEEDER_V1 = "v1"


def pin_null_leadfeeder_rows_to_v1(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # The isnull guard keeps it idempotent (safe under retries) and never overwrites a concrete pin.
    ExternalDataSource.objects.filter(source_type=LEADFEEDER_SOURCE_TYPE, api_version__isnull=True).update(
        api_version=LEADFEEDER_V1
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0130_repin_loop_returns_api_version"),
    ]

    operations = [
        # Reverse is a no-op: after this runs, the pinned rows are indistinguishable from natively
        # created v1 sources, so nulling "v1" pins would also destroy legitimate creation-time stamps.
        migrations.RunPython(pin_null_leadfeeder_rows_to_v1, migrations.RunPython.noop, elidable=True),
    ]
