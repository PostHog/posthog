from django.db import migrations

# LlamaCloud now files its v1 API under "Deprecated (v1)". This source has always read LlamaCloud's
# v2-generation endpoints on the wire — the framework label was the unversioned `v1` default. The
# source declares `v2` as the default and marks the legacy `v1` label deprecated. There is no
# per-version dispatch, so `v1` and `v2` resolve to byte-identical requests; this repins existing
# source-level pins from `v1` to `v2` so they stop carrying a deprecated label. It is a pure relabel,
# not a version move — no data/schema transform is needed.
LLAMA_CLOUD_SOURCE_TYPE = "LlamaCloud"
OLD_VERSION = "v1"
NEW_VERSION = "v2"


def repin_llama_cloud_v1_to_v2(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides
    # are user-managed (a customer intentionally pinned that schema) and are left alone — the
    # schema-level deprecation warning prompts the user to migrate those.
    #
    # NULL pins already resolve to the source's `default_version` (`v2`), so they need no update.
    # Matching only `api_version="v1"` keeps this idempotent: a second run matches nothing.
    ExternalDataSource.objects.filter(source_type=LLAMA_CLOUD_SOURCE_TYPE, api_version=OLD_VERSION).update(
        api_version=NEW_VERSION
    )


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0173_repair_legacy_full_sync_type"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, these rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate `v2` pins made after this ran.
        migrations.RunPython(repin_llama_cloud_v1_to_v2, migrations.RunPython.noop, elidable=True),
    ]
