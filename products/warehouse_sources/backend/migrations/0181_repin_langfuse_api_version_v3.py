from django.db import migrations

# Langfuse Cloud stops serving the legacy `/traces` and `/sessions` read routes on 2026-11-16.
# The source's v1 and v2 labels both read them, and send identical requests for every other table.
# v3 keeps that wire for every other table and drops `traces` and `sessions`, because their
# replacement returns observation rows, not trace or session objects.
#
# A source that syncs neither table loses nothing on v3, so this repins it. A source that syncs
# either table would lose that table on repin, so it stays on its pin. The PR documents the manual
# path for those sources.
LANGFUSE_SOURCE_TYPE = "Langfuse"
OLD_VERSIONS = ("v1", "v2")
NEW_VERSION = "v3"
LEGACY_ONLY_TABLES = ("traces", "sessions")


def repin_langfuse_to_v3(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # `deleted` is nullable, and a NULL row is live, so exclude only rows marked deleted.
    sources_syncing_legacy_tables = (
        ExternalDataSchema.objects.filter(
            source__source_type=LANGFUSE_SOURCE_TYPE,
            source__api_version__in=OLD_VERSIONS,
            name__in=LEGACY_ONLY_TABLES,
            should_sync=True,
        )
        .exclude(deleted=True)
        .values("source_id")
    )

    # Only the source-level pin moves. Schema-level `ExternalDataSchema.api_version` overrides are
    # user-managed and stay as they are. NULL pins already resolve to the new default. Matching only
    # the old labels keeps this idempotent: a second run matches only the excluded sources.
    ExternalDataSource.objects.filter(source_type=LANGFUSE_SOURCE_TYPE, api_version__in=OLD_VERSIONS).exclude(
        id__in=sources_syncing_legacy_tables
    ).update(api_version=NEW_VERSION)


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0180_repin_incident_io_api_version_v3")]

    operations = [
        # Reverse is a no-op: repinned rows are indistinguishable from natively created v3 rows, so a
        # blanket downgrade would clobber legitimate v3 pins.
        migrations.RunPython(repin_langfuse_to_v3, migrations.RunPython.noop, elidable=False),
    ]
