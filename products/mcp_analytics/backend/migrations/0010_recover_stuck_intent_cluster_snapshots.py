from datetime import UTC, datetime

from django.db import migrations

# The intent-clustering task queue had no worker deployed until 2026-07-27, so
# every recompute dispatched in that window sat unhandled: the snapshot stayed
# COMPUTING until the stale sweep froze it to ERROR, and its error message never
# changed again. Reset those pre-fix rows to IDLE so the tab offers a fresh run
# (or renders the last good clusters) instead of a permanent, stale error.
CUTOFF = datetime(2026, 7, 28, tzinfo=UTC)


def recover_stuck_snapshots(apps, schema_editor):
    MCPIntentClusterSnapshot = apps.get_model("mcp_analytics", "MCPIntentClusterSnapshot")
    MCPIntentClusterSnapshot.objects.filter(
        status__in=["error", "computing"],
        updated_at__lt=CUTOFF,
    ).update(status="idle", error_message="")


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_analytics", "0009_mcpintentembeddingcache"),
    ]

    operations = [
        migrations.RunPython(recover_stuck_snapshots, migrations.RunPython.noop),
    ]
