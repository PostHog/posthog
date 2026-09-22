from django.db import migrations


class Migration(migrations.Migration):
    """Drop the old team-wide (service_account, gateway_server) uniqueness now
    that the per-user unique index from 0024 enforces the widened key.

    Reversing this is only safe while at most one member holds a grant per
    (agent, server). Once a second member has shared the same server with the
    same agent, restoring uniq_agent_server_access fails on duplicate keys, and
    the rows would have to be deduplicated by hand first.

    Kept separate from 0024 so this regular DDL keeps transaction rollback
    safety while the concurrent index build runs with atomic = False.
    """

    dependencies = [
        ("mcp_store", "0024_personal_agent_server_access"),
    ]

    operations = [
        # DROP CONSTRAINT is a fast metadata-only change (brief ACCESS
        # EXCLUSIVE lock, no table scan), so it needs no concurrent variant.
        migrations.RemoveConstraint(
            model_name="mcpserviceaccountserveraccess",
            name="uniq_agent_server_access",
        ),
    ]
