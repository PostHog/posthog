from django.db import migrations


class Migration(migrations.Migration):
    """Phase 2 of the MCPServer -> MCPServerTemplate + per-installation DCR cutover, state-only.

    0007 state-removed the ``server`` FK on ``MCPServerInstallation`` and
    ``MCPOAuthState`` while leaving the physical ``server_id`` columns in
    place so the previous deploy could continue writing during the rollout.
    This migration removes the ``MCPServer`` model from Django state so the
    ORM, admin, and application code no longer see it — but leaves the
    underlying ``mcp_store_mcpserver`` table and both ``server_id`` columns
    in the database.

    Rationale: at PostHog's scale, physical ``DROP COLUMN`` / ``DROP TABLE``
    briefly hold an ``ACCESS EXCLUSIVE`` lock, which can queue traffic on
    hot tables. These objects are already orphaned — nothing reads or writes
    them — so leaving them in place is harmless. A separate PR can reclaim
    the storage during a maintenance window if desired.
    """

    dependencies = [
        ("mcp_store", "0007_migrate_mcp_creds_to_per_installation"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="MCPServer"),
            ],
            database_operations=[],
        ),
    ]
