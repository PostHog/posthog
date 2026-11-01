from django.db import migrations

# Profound is phasing out its V1 report endpoints (`/v1/reports/*`) in favor of `/v2/reports/*`, and
# has not announced a sunset date yet. This source has read `/v2/reports/*` under both labels since
# `v2` was added: there is no per-version dispatch, so `v1` and `v2` resolve to byte-identical
# requests. The source marks `v1` deprecated, and this repins existing source-level pins from `v1` to
# `v2` so they stop carrying a deprecated label. It is a pure relabel, not a version move, so no
# data or schema transform is needed.
PROFOUND_SOURCE_TYPE = "Profound"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_profound_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Source-level pin only. Schema-level `ExternalDataSchema.api_version` overrides are user-managed
    # (a customer intentionally pinned that schema) and are left alone. The schema-level deprecation
    # warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (`v2`), so they need no update.
    # Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=PROFOUND_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0188_reset_trunkio_v2_failing_tests"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate `v2` pins made after this ran.
        migrations.RunPython(repin_profound_v1_to_v2, migrations.RunPython.noop, elidable=True),
    ]
