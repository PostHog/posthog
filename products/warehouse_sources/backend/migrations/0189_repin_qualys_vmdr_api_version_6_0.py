from django.db import migrations

# Qualys retires the Host List and VM Scan 2.0 routes in December 2026 (End of Life), and source-level
# "4.0" pins still call them, so those pins move to "6.0". The whole cohort is safe to script: on 6.0
# the hosts and host_list_detection tables call /api/6.0/, and the scans and appliances tables call
# /api/3.0/. All four keep basic auth with the stored credentials, keep their primary keys, and only
# gain optional XML elements, which land as new columns. knowledge_base already uses the 4.0 JWT
# route on both pins, so no source needs a credential it doesn't already have.
#
# Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides are
# user-managed by design (a customer intentionally pinned that schema) and are left alone — the
# schema-level deprecation warning prompts the user to migrate those.
QUALYS_VMDR_SOURCE_TYPE = "QualysVmdr"
QUALYS_VMDR_API_VERSION_4_0 = "4.0"
QUALYS_VMDR_API_VERSION_6_0 = "6.0"


def repin_qualys_vmdr_4_0_to_6_0(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Idempotent: matches only explicit "4.0" pins, so a second run finds none. NULL pins already
    # resolve to the "6.0" default, and "2.0" pins wait on the gateway URL manual path, so neither
    # is touched.
    ExternalDataSource.objects.filter(
        source_type=QUALYS_VMDR_SOURCE_TYPE, api_version=QUALYS_VMDR_API_VERSION_4_0
    ).update(api_version=QUALYS_VMDR_API_VERSION_6_0)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0188_reset_trunkio_v2_failing_tests"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, "6.0" rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate "6.0" pins.
        migrations.RunPython(repin_qualys_vmdr_4_0_to_6_0, migrations.RunPython.noop, elidable=False),
    ]
