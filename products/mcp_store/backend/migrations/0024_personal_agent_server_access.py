from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    """Widen the agent-grant uniqueness key so each member holds their own grant
    for an (agent, server) pair. The old team-wide constraint is dropped in the
    next migration, once this index enforces the widened key.

    ``user`` stays nullable through this release: pods on the previous release
    keep inserting grants without it during the rolling deploy. Nulls are
    distinct under a Postgres unique index, so such a row does not collide
    with the granter's real row. That is an acceptable transient state because
    new code always writes ``user`` and every read path either filters on an
    explicit user id or excludes ``user__isnull=True``, so a null row can
    neither be mounted by an agent nor reach the non-nullable ``user`` /
    ``shared_by`` serializer fields.
    """

    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("mcp_store", "0023_backfill_agent_access_user"),
    ]

    operations = [
        # Built CONCURRENTLY because this table is written by both old and new
        # pods during the rolling deploy this migration runs in, and a plain
        # AddConstraint would build its backing index under an ACCESS EXCLUSIVE
        # lock that blocks those writes. Built before the old constraint is
        # dropped so the table is never left without uniqueness protection; the
        # old, narrower key implies this one, so the build cannot fail on
        # duplicates. The helper disables lock_timeout and recovers from an
        # invalid leftover build, so bin/migrate retries are safe. Django state
        # gets the matching UniqueConstraint while the database enforces it via
        # the unique index alone.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="mcpserviceaccountserveraccess",
                    constraint=models.UniqueConstraint(
                        fields=("service_account", "gateway_server", "user"),
                        name="uniq_agent_server_access_per_user",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="uniq_agent_server_access_per_user",
                    table_name="mcp_store_mcpserviceaccountserveraccess",
                    columns="(service_account_id, gateway_server_id, user_id)",
                    unique=True,
                ),
            ],
        ),
    ]
