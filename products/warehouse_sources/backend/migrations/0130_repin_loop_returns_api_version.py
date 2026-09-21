from django.db import migrations

# Loop is phasing out the `v1` alias, which resolves to the `2026-07` GA release. The source now
# defaults new instances to `2026-07`; this repins existing source-level pins from the alias to
# the explicit date version so they stop tracking the alias. `v1` and `2026-07` serve identical
# responses (the alias resolves to that exact release), so the repin is behavior-preserving.
LOOP_RETURNS_SOURCE_TYPE = "LoopReturns"
OLD_VERSION = "v1"
NEW_VERSION = "2026-07"


def repin_loop_returns_v1_to_2026_07(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version`
    # overrides are user-managed (a customer intentionally pinned that schema) and are left
    # alone — the schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (now `2026-07`), so they need
    # no update. Matching only `api_version="v1"` keeps this idempotent: a second run matches
    # nothing.
    ExternalDataSource.objects.filter(source_type=LOOP_RETURNS_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0129_pin_openweather_v2_5"),
    ]

    operations = [
        # Reverse is a no-op: nulling or downgrading pins would move customers back onto the
        # deprecated alias and clobber any deliberate post-migration pins.
        migrations.RunPython(repin_loop_returns_v1_to_2026_07, migrations.RunPython.noop, elidable=False),
    ]
