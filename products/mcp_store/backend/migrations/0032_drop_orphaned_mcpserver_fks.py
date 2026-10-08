from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Drop the two foreign keys pointing at mcp_store_mcpserver, which nothing owns any more.

    0007 took the `server` fields out of Django state with database_operations=[], and 0008
    took the MCPServer model out of state as well. Both left their tables and columns in
    place. The foreign keys stayed, and no later migration removes them.

    0008 reasoned that leaving the objects was harmless because nothing reads or writes them.
    That holds for the columns. It does not hold for the constraints: a foreign key fires when
    the parent row is deleted, not when anyone reads it. Nothing deletes these parent rows
    today, because MCPServer is out of Django state, so this is a trap rather than a live
    fault. Any later cleanup of mcp_store_mcpserver would spring it.

    The columns stay. Only the constraints go.
    """

    dependencies = [
        ("mcp_store", "0031_alter_mcpoauthstate_team_and_more"),
    ]

    operations = [
        DropForeignKey("mcp_store_mcpserverinstallation", column="server_id"),
        DropForeignKey("mcp_store_mcpoauthstate", column="server_id"),
    ]
