from django.db import migrations

# Calendly retired the legacy v1 API (vendor sunset 2025-08-27). Both declared labels resolve to the
# same live host (`api.calendly.com` + Bearer PAT) — the original "v1" pin already hit it — so repinning
# source-level pins onto v2 is a plain label move with no data/schema transform. Filtering on the exact
# old value keeps it idempotent; schema-level overrides (`ExternalDataSchema.api_version`) are
# intentionally customer-pinned and left untouched.
CALENDLY_SOURCE_TYPE = "Calendly"
DEPRECATED_VERSION = "v1"
TARGET_VERSION = "v2"


def repin_calendly_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # NULL pins already resolve to the source's `default_version` (now v2), so only rows still pinned to
    # the exact deprecated value need moving.
    ExternalDataSource.objects.filter(source_type=CALENDLY_SOURCE_TYPE, api_version=DEPRECATED_VERSION).update(
        api_version=TARGET_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0105_repin_harvey_api_version_v2")]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate v2 pins.
        migrations.RunPython(repin_calendly_api_version, migrations.RunPython.noop, elidable=False),
    ]
