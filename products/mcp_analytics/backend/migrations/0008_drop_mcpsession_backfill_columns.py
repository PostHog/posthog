from django.db import migrations


class Migration(migrations.Migration):
    # Phase 2 of a two-phase column drop (see safe-django-migrations.md "Dropping Columns").
    # Migration 0007 removed these fields from Django's model state; this one performs the
    # actual DROP COLUMN now that no deployed code references them. It is database-only —
    # the model state is already correct, so there are no state operations and a plain
    # RemoveField would fail (the fields no longer exist in state).
    #
    # Dropping session_end cascades the (team, -session_end) index, but we drop it
    # explicitly first so the intent is obvious. DROP COLUMN takes a brief ACCESS EXCLUSIVE
    # lock and is metadata-only (no table rewrite); the table is small and low-traffic.

    dependencies = [
        ("mcp_analytics", "0007_alter_mcpsession_options_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DROP INDEX IF EXISTS posthog_mcp_team_id_b561f4_idx;
                ALTER TABLE posthog_mcp_session
                    DROP COLUMN IF EXISTS session_start,
                    DROP COLUMN IF EXISTS session_end,
                    DROP COLUMN IF EXISTS duration_seconds,
                    DROP COLUMN IF EXISTS tools_used,
                    DROP COLUMN IF EXISTS tool_call_count,
                    DROP COLUMN IF EXISTS distinct_id,
                    DROP COLUMN IF EXISTS mcp_client_name;
            """,
            # Structural restore only — the dropped data is not recoverable. Re-adds the
            # columns as they stood just before the drop (all nullable) and recreates the index.
            reverse_sql="""
                ALTER TABLE posthog_mcp_session
                    ADD COLUMN IF NOT EXISTS session_start timestamptz NULL,
                    ADD COLUMN IF NOT EXISTS session_end timestamptz NULL,
                    ADD COLUMN IF NOT EXISTS duration_seconds integer NULL,
                    ADD COLUMN IF NOT EXISTS tools_used varchar(200)[] NULL,
                    ADD COLUMN IF NOT EXISTS tool_call_count integer NULL,
                    ADD COLUMN IF NOT EXISTS distinct_id varchar(400) NULL,
                    ADD COLUMN IF NOT EXISTS mcp_client_name varchar(200) NULL;
                CREATE INDEX IF NOT EXISTS posthog_mcp_team_id_b561f4_idx
                    ON posthog_mcp_session (team_id, session_end DESC);
            """,
        ),
    ]
