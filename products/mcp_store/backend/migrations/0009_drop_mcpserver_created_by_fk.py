from django.db import migrations


class Migration(migrations.Migration):
    """Drop the orphan ``mcp_store_mcpserver.created_by_id`` FK to ``posthog_user``.

    0008 removed ``MCPServer`` from Django state but left the physical
    ``mcp_store_mcpserver`` table in the database. That table still carried
    a foreign key from ``created_by_id`` to ``posthog_user`` (inherited from
    ``CreatedMetaFields``), which breaks test teardown: Postgres refuses to
    ``TRUNCATE posthog_user`` without ``CASCADE`` while any other table
    still references it, and the orphan table is no longer in Django's
    model graph for the test harness to include in its truncate set.

    This migration drops just that one FK constraint. The ``created_by_id``
    column and the table itself remain in place — only the foreign key
    relationship is severed, so no hot table is touched. ``DROP CONSTRAINT``
    is metadata-only and holds ``ACCESS EXCLUSIVE`` on the (dead, unqueried)
    orphan table for microseconds.

    The constraint name is looked up dynamically because Django's
    auto-generated FK constraint names embed a hash that varies across
    environments. Using a ``DO`` block keeps this idempotent and robust.
    """

    dependencies = [
        ("mcp_store", "0008_drop_legacy_mcpserver"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            DECLARE
                constraint_name TEXT;
            BEGIN
                FOR constraint_name IN
                    SELECT conname
                    FROM pg_constraint c
                    JOIN pg_class t ON c.conrelid = t.oid
                    JOIN pg_class ref ON c.confrelid = ref.oid
                    WHERE t.relname = 'mcp_store_mcpserver'
                      AND ref.relname = 'posthog_user'
                      AND c.contype = 'f'
                LOOP
                    EXECUTE format(
                        'ALTER TABLE mcp_store_mcpserver DROP CONSTRAINT IF EXISTS %I',
                        constraint_name
                    );
                END LOOP;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
