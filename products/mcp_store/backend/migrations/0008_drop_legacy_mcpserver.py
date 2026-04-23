from django.db import migrations


class Migration(migrations.Migration):
    """Phase 2 of the MCPServer -> MCPServerTemplate + per-installation DCR cutover.

    Migration 0007 removed the ``server`` FK from Django's state on both
    ``MCPServerInstallation`` and ``MCPOAuthState`` but left the underlying
    columns in place so the previous deploy (still holding the field in its
    ORM) could continue to write to them during the rolling deploy.

    By the time this migration runs the old code is drained — no writer
    touches ``server_id`` anymore — so it is safe to:

      1. Drop the now-orphan ``server_id`` columns (which also drops the FK
         constraints that would otherwise pin the mcp_store_mcpserver table
         in place).
      2. Drop the legacy ``mcp_store_mcpserver`` table.
      3. Remove the ``MCPServer`` model from Django state.

    Column drops carry the ``-- drop-column-ignore`` hint so the backend
    migration safety check permits them; the hint is the project convention
    for post-rollout column removals.
    """

    dependencies = [
        ("mcp_store", "0007_migrate_mcp_creds_to_per_installation"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="MCPServer"),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE mcp_store_mcpserverinstallation "
                        "DROP COLUMN IF EXISTS server_id; -- drop-column-ignore"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql=("ALTER TABLE mcp_store_mcpoauthstate DROP COLUMN IF EXISTS server_id; -- drop-column-ignore"),
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql="DROP TABLE IF EXISTS mcp_store_mcpserver;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
