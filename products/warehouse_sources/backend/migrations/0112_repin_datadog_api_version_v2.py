from django.db import migrations

# The Datadog source defaults new instances to "v2" and marks "v1" deprecated, but sources created
# before that flip are still pinned "v1" and so render the version-deprecation warning. Datadog
# serves each resource under a fixed API version — the source reads logs/audit_logs/events/users/
# incidents/downtimes from /api/v2 and dashboards/monitors/slos/synthetic_tests from /api/v1 (those
# four have no v2 list endpoint) — so both labels resolve to identical request paths. Moving the pin
# is therefore lossless: no credential, resource-set, or schema change, and no resync.
DATADOG_SOURCE_TYPE = "Datadog"
DEPRECATED_VERSION = "v1"
TARGET_VERSION = "v2"


def repin_datadog_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated version. NULL pins already resolve to the
    # source's `default_version` (now v2), so they need no update. Filtering on the exact old value
    # keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (`ExternalDataSchema.api_version`) are intentionally customer-pinned and are left untouched;
    # the schema-level warning has its own self-serve version picker.
    ExternalDataSource.objects.filter(source_type=DATADOG_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0111_repin_zonka_feedback_api_version")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate v2 pins.
        migrations.RunPython(repin_datadog_api_version, migrations.RunPython.noop, elidable=False),
    ]
