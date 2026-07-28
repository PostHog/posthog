from django.db import migrations

# Datadog's v1 vendor API version is deprecated (see DatadogSource.deprecated_versions); new
# sources are now stamped v2. This repins existing source-level pins off the deprecated label.
#
# Safe as a plain UPDATE with no data or schema transform: Datadog serves each resource under a
# fixed API version regardless of this pin (dashboards/monitors/slos/synthetic_tests have no v2
# list endpoint and stay on /api/v1; every other table is already read at /api/v2), so v2 issues
# the identical requests v1 did. The source auto-infers its schema, so no columns change either.
DEPRECATED_API_VERSION = "v1"
NEW_API_VERSION = "v2"


def repin_datadog_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pins only. ExternalDataSchema.api_version overrides are user-managed by design
    # and left untouched. Matching the deprecated value keeps this idempotent under retries and
    # never disturbs rows already pinned to another version.
    ExternalDataSource.objects.filter(source_type="Datadog", api_version=DEPRECATED_API_VERSION).update(
        api_version=NEW_API_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0104_easybill_source"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, v2 rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate native v2 pins.
        migrations.RunPython(repin_datadog_api_version, migrations.RunPython.noop, elidable=True),
    ]
