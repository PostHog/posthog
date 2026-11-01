from django.db import migrations

# Rippling calls its V1 API (api.rippling.com) legacy, with no published sunset date. This source has
# always read the v2 REST API (rest.ripplingapis.com) and sends no version header, so the `v1` and
# `v2` labels resolve to byte-identical requests. This repins source-level pins from `v1` to `v2` so
# they stop carrying a deprecated label. It is a pure relabel, not a version move: no data/schema
# transform is needed.
RIPPLING_SOURCE_TYPE = "Rippling"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_rippling_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides
    # are user-managed and are left alone. NULL pins already resolve to `v2`, and matching only
    # `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=RIPPLING_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0188_reset_trunkio_v2_failing_tests"),
    ]

    operations = [
        # Reverse is a no-op: repinned rows are indistinguishable from natively-created `v2` pins.
        migrations.RunPython(repin_rippling_v1_to_v2, migrations.RunPython.noop, elidable=True),
    ]
