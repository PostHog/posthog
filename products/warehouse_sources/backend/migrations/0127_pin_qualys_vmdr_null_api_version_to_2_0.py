from django.db import migrations

# Qualys VMDR's default vendor API version flips to "4.0" in the same change that adds this
# migration. Existing rows were pinned "2.0" by migration 0075, but a row created via a direct-ORM
# path that bypasses creation-time stamping could still have a NULL `api_version`, and a NULL pin
# resolves to `default_version` — so it would silently follow the flip to 4.0. On 4.0 the
# knowledge_base table authenticates with a gateway-minted JWT (a gateway URL the stored basic-auth
# credentials don't carry), so an unpinned source moved to 4.0 would fail that table. Pin any such
# rows back to "2.0" so the flip only affects newly created sources.
#
# This does NOT repin "2.0" customers to "4.0": that migration is not safe to script (4.0 needs a
# gateway URL that can't be derived from the stored credentials), so it is documented as a manual
# path in the PR. Only the source-level pin is touched — schema-level `ExternalDataSchema.api_version`
# overrides are user-managed (a customer intentionally pinned that schema) and are left alone; the
# schema-level deprecation warning prompts the user to migrate those.
QUALYS_VMDR_SOURCE_TYPE = "QualysVmdr"
QUALYS_VMDR_API_VERSION_2_0 = "2.0"


def pin_null_qualys_vmdr_rows_to_2_0(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # The isnull guard keeps it idempotent (safe under retries) and never overwrites a concrete pin.
    ExternalDataSource.objects.filter(source_type=QUALYS_VMDR_SOURCE_TYPE, api_version__isnull=True).update(
        api_version=QUALYS_VMDR_API_VERSION_2_0
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0126_oom_created_idx"),
    ]

    operations = [
        # Reverse is a no-op: after this runs, the pinned rows are indistinguishable from natively
        # created 2.0 sources, so nulling "2.0" pins would also destroy legitimate creation-time stamps.
        migrations.RunPython(pin_null_qualys_vmdr_rows_to_2_0, migrations.RunPython.noop, elidable=True),
    ]
