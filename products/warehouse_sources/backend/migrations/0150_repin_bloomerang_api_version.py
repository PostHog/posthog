from django.db import migrations

# Bloomerang has deprecated its v1 REST API. This source has always spoken the current v2 REST API
# on the wire (BASE_URL ends in `/v2`) — the framework label was the unversioned `v1` default. The
# source now declares `v2` as the explicit default and marks the legacy `v1` label deprecated. There
# is no per-version dispatch, so `v1` and `v2` resolve to byte-identical requests; this repins
# existing source-level pins from `v1` to `v2` so they stop carrying a deprecated label. It is a pure
# relabel, not a version move — no data/schema transform is needed.
BLOOMERANG_SOURCE_TYPE = "Bloomerang"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_bloomerang_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides
    # are user-managed (a customer intentionally pinned that schema) and are left alone — the
    # schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (now `v2`), so they need no update.
    # Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=BLOOMERANG_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0149_datawarehousetable_created_via"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate `v2` pins made after this ran.
        migrations.RunPython(repin_bloomerang_v1_to_v2, migrations.RunPython.noop, elidable=True),
    ]
