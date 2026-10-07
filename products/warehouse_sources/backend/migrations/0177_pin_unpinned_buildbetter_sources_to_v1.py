from django.db import migrations
from django.db.models import Q

# BuildBetter's default version moves from `v1` (GraphQL) to `v3` (REST for interviews, attendees
# and transcripts). The versions are not request-identical: `v3` keys interviews by public UUID
# instead of the GraphQL bigint id. An unpinned source resolves to the default, so it would move to
# `v3` silently and merge UUID-keyed rows into tables built from bigint ids. Every unpinned source
# was created when `v1` was the only version, so this pins it to `v1` explicitly.
#
# Rows already pinned to `v1` stay on `v1`: the vendor deprecated GraphQL without a sunset date, and
# moving to `v3` changes primary keys, so that move is a manual re-sync, not a scripted repin.
BUILDBETTER_SOURCE_TYPE = "BuildBetter"
LEGACY_VERSION = "v1"


def pin_unpinned_buildbetter_sources_to_v1(apps, schema_editor):
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    # Only the source-level pin is touched. Schema-level `ExternalDataSchema.api_version` overrides
    # are user-managed and are left alone. Matching only NULL/empty pins keeps this idempotent.
    ExternalDataSource.objects.filter(
        Q(api_version__isnull=True) | Q(api_version=""), source_type=BUILDBETTER_SOURCE_TYPE
    ).update(api_version=LEGACY_VERSION)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0176_repin_lightspeed_retail_api_version_2026_07"),
    ]

    operations = [
        # Reverse is a no-op: once pinned, these rows are indistinguishable from sources pinned to
        # `v1` by the create path, so clearing them would move legitimate `v1` pins to the default.
        migrations.RunPython(pin_unpinned_buildbetter_sources_to_v1, migrations.RunPython.noop, elidable=True),
    ]
