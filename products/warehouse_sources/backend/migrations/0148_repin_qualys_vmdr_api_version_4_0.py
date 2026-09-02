from django.db import migrations

# Qualys sunset KnowledgeBase 2.0 on 2026-06-30 (End of Life), so source-level "2.0" pins must move
# to "4.0". Most of the move is safe to script: the hosts, host_list_detection, and scans tables
# send a byte-identical request on 2.0 and 4.0 (they stay on the FO API's own /api/2.0/ routes with
# basic auth regardless of the source pin), so repinning those sources is not a version move on the
# wire — only a relabel.
#
# The knowledge_base table is the exception: on 4.0 it authenticates with a gateway-minted JWT, which
# needs a gateway URL the stored basic-auth credentials don't carry. A source whose knowledge_base
# schema follows the source pin therefore can't be moved to 4.0 automatically — that repin is a
# manual path (add a gateway URL, then repin), documented in the PR. Such sources are excluded here
# and left on "2.0"; the version deprecation warning surfaces the pending migration.
#
# Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides are
# user-managed by design (a customer intentionally pinned that schema) and are left alone — the
# schema-level deprecation warning prompts the user to migrate those. A knowledge_base schema with
# its own override does not follow the source pin, so it never blocks a source's repin.
QUALYS_VMDR_SOURCE_TYPE = "QualysVmdr"
QUALYS_VMDR_API_VERSION_2_0 = "2.0"
QUALYS_VMDR_API_VERSION_4_0 = "4.0"


def repin_qualys_vmdr_2_0_to_4_0(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")
    ExternalDataSchema = apps.get_model("warehouse_sources", "ExternalDataSchema")

    # Sources whose knowledge_base sync follows the source pin: moving them to 4.0 would need a
    # gateway URL that isn't derivable from stored credentials, so hold them on 2.0 (manual path).
    gateway_dependent_source_ids = (
        ExternalDataSchema.objects.filter(
            source__source_type=QUALYS_VMDR_SOURCE_TYPE,
            name="knowledge_base",
            should_sync=True,
            api_version__isnull=True,
        )
        .exclude(deleted=True)
        .values_list("source_id", flat=True)
    )

    # Idempotent: matches only explicit "2.0" pins, so a second run finds none. NULL pins already
    # resolve to the "4.0" default (migration 0127 pinned any pre-existing NULL rows to "2.0"), so
    # there is nothing to touch there.
    ExternalDataSource.objects.filter(
        source_type=QUALYS_VMDR_SOURCE_TYPE, api_version=QUALYS_VMDR_API_VERSION_2_0
    ).exclude(id__in=gateway_dependent_source_ids).update(api_version=QUALYS_VMDR_API_VERSION_4_0)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0147_add_kalshi_source"),
    ]

    operations = [
        # Reverse is a no-op: once repinned, "4.0" rows are indistinguishable from natively-created
        # ones, so a blanket downgrade would clobber legitimate "4.0" pins and move customers back
        # onto the sunset "2.0" version.
        migrations.RunPython(repin_qualys_vmdr_2_0_to_4_0, migrations.RunPython.noop, elidable=False),
    ]
