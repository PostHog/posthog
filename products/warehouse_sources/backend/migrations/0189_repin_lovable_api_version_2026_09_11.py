from django.db import migrations

# Lovable lists 2026-09-11 as its only supported API version and serves it to requests without a
# `Lovable-Version` header. The v1 label sends no header, so v1 pins already receive 2026-09-11
# responses through a request path built for the old wire.
#
# 2026-09-11 has no credit history endpoint, so no source can sync that table today and the repin
# loses nothing there. Lovable still serves project collaborators, but the source's 2026-09-11 table
# set does not include them. A source that syncs that table would lose it on repin, so it stays on
# its pin. The PR documents the manual path for those sources.
LOVABLE_SOURCE_TYPE = "Lovable"
OLD_VERSION = "v1"
NEW_VERSION = "2026-09-11"
V1_ONLY_TABLES = ("ProjectCollaborators",)


def repin_lovable_to_2026_09_11(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # `deleted` is nullable, and a NULL row is live, so exclude only rows marked deleted.
    sources_syncing_v1_only_tables = (
        ExternalDataSchema.objects.filter(
            source__source_type=LOVABLE_SOURCE_TYPE,
            source__api_version=OLD_VERSION,
            name__in=V1_ONLY_TABLES,
            should_sync=True,
        )
        .exclude(deleted=True)
        .values("source_id")
    )

    # Only the source-level pin moves. Schema-level `ExternalDataSchema.api_version` overrides are
    # user-managed and stay as they are. NULL pins already resolve to the new default. Matching only
    # the old label keeps this idempotent: a second run matches only the excluded sources.
    ExternalDataSource.objects.filter(source_type=LOVABLE_SOURCE_TYPE, api_version=OLD_VERSION).exclude(
        id__in=sources_syncing_v1_only_tables
    ).update(api_version=NEW_VERSION)


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0188_reset_trunkio_v2_failing_tests")]

    operations = [
        # Reverse is a no-op: repinned rows are indistinguishable from natively created 2026-09-11
        # rows, so a blanket downgrade would clobber legitimate pins.
        migrations.RunPython(repin_lovable_to_2026_09_11, migrations.RunPython.noop, elidable=False),
    ]
