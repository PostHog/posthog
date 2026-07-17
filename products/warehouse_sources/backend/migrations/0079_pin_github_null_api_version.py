from django.db import migrations

# The version GitHub sources resolved to before 2026-03-10 became the source's default. Frozen here
# (not imported from the source class) so the backfill stays deterministic and independent of app code.
GITHUB_LEGACY_API_VERSION = "2022-11-28"


def pin_github_null_api_version(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # 0075 pinned every GitHub row that existed then, and creation stamps `default_version` since.
    # Any row still on a NULL pin would otherwise resolve to the source default at sync time, so the
    # default flip to 2026-03-10 would silently move it off 2022-11-28 — the exact silent version
    # change resolve_api_version exists to prevent. Pin those stragglers to their current effective
    # version so the flip only affects newly created sources. The isnull guard keeps it idempotent
    # and never overwrites a real pin.
    ExternalDataSource.objects.filter(source_type="Github", api_version__isnull=True).update(
        api_version=GITHUB_LEGACY_API_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0078_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        # Reverse is a no-op: nulling pins that merely match the legacy version would also destroy
        # legitimate creation-time stamps, same reasoning as 0075.
        migrations.RunPython(pin_github_null_api_version, migrations.RunPython.noop, elidable=True),
    ]
