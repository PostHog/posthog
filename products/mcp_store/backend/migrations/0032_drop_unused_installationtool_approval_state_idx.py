from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("mcp_store", "0031_alter_mcpoauthstate_team_and_more"),
    ]

    operations = [
        # No reader filters on approval_state. Every query selects it as a value and
        # branches in Python, so the only scans this index can serve are installation
        # lookups, which the unique_together on (installation, tool_name) and the
        # sibling (installation, removed_at) index already cover. What it still costs
        # is write amplification on the per-installation tool sync.
        SafeRemoveIndexConcurrently(
            model_name="mcpserverinstallationtool",
            name="mcp_store_m_install_2b5d15_idx",
        ),
    ]
