from django.db import migrations

# Zonka deprecated its older API generation (vendor "API 2.0") in favor of the current v2.1 API. The
# source now defaults new instances to v2.1, and our legacy `v1` label already targets the current
# host (apis.zonkafeedback.com) — there is no per-version request dispatch, so v1 and v2.1 resolve to
# identical requests here. The repin is a pure pin move with no data/schema transform.
ZONKA_FEEDBACK_SOURCE_TYPE = "ZonkaFeedback"
DEPRECATED_VERSION = "v1"
TARGET_VERSION = "v2.1"


def repin_zonka_feedback_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only touch source-level pins still on the deprecated version. NULL pins already resolve to the
    # source's `default_version` (now v2.1), so they need no update. Filtering on the exact old value
    # keeps this idempotent — a re-run matches nothing. Schema-level overrides
    # (`ExternalDataSchema.api_version`) are intentionally customer-pinned and are left untouched.
    ExternalDataSource.objects.filter(source_type=ZONKA_FEEDBACK_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0110_pin_shipstation_null_api_version_to_v1")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate v2.1 pins.
        migrations.RunPython(repin_zonka_feedback_api_version, migrations.RunPython.noop, elidable=False),
    ]
