from django.db import migrations, models


class Migration(migrations.Migration):
    """Widen the agent-grant uniqueness key so each member holds their own grant
    for an (agent, server) pair.

    Reversing this is only safe while at most one member holds a grant per
    (agent, server). Once a second member has shared the same server with the
    same agent, restoring uniq_agent_server_access fails on duplicate keys, and
    the rows would have to be deduplicated by hand first.

    ``user`` stays nullable through this release: pods on the previous release
    keep inserting grants without it during the rolling deploy. Nulls are
    distinct under a Postgres unique constraint, so such a row does not collide
    with the granter's real row. That is an acceptable transient state because
    new code always writes ``user`` and every read path either filters on an
    explicit user id or excludes ``user__isnull=True``, so a null row can
    neither be mounted by an agent nor reach the non-nullable ``user`` /
    ``shared_by`` serializer fields.
    """

    dependencies = [
        ("mcp_store", "0023_backfill_agent_access_user"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="mcpserviceaccountserveraccess",
            name="uniq_agent_server_access",
        ),
        migrations.AddConstraint(
            model_name="mcpserviceaccountserveraccess",
            constraint=models.UniqueConstraint(
                fields=("service_account", "gateway_server", "user"),
                name="uniq_agent_server_access_per_user",
            ),
        ),
    ]
