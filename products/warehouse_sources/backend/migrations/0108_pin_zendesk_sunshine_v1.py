from django.db import migrations

# Zendesk Sunshine now defaults to v2 (the current custom objects API). v2 exposes a different
# table set from the legacy v1 Sunshine API (no relationship/policy tables, records reshaped under
# `custom_object_fields`), so a source moving from v1 to v2 is a lossy transition, not an in-place
# `api_version` flip: the next discovery cycle would orphan the v1 tables and start the v2 ones
# fresh. That migration is therefore intentionally NOT scripted — the manual path is documented in
# the PR and run per-source by a human.
#
# This migration only backs out the NULL cohort from the default flip. A NULL `api_version` resolves
# to `default_version`, which just moved v1 -> v2, so any Sunshine source created without an explicit
# pin (direct-ORM/seeder paths that bypass the API's create-time stamping) would silently jump onto
# v2's divergent table set. Pinning those rows to v1 keeps them on the version they were syncing.
ZENDESK_SUNSHINE_SOURCE_TYPE = "ZendeskSunshine"
V1_VERSION = "v1"


def pin_zendesk_sunshine_v1(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pins only. Filtering on NULL keeps this idempotent — a re-run matches nothing,
    # and rows already carrying an explicit pin (v1 or v2) are left as their owner set them.
    # Schema-level overrides (`ExternalDataSchema.api_version`) are customer-managed and untouched.
    ExternalDataSource.objects.filter(source_type=ZENDESK_SUNSHINE_SOURCE_TYPE, api_version__isnull=True).update(
        api_version=V1_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0107_repin_marketstack_api_version_v2")]

    operations = [
        # Reverse is a no-op: once pinned, a v1 row is indistinguishable from one natively stamped v1,
        # so re-nulling would wrongly clear legitimate explicit pins too.
        migrations.RunPython(pin_zendesk_sunshine_v1, migrations.RunPython.noop, elidable=False),
    ]
