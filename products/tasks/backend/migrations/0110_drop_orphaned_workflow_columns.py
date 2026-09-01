from django.db import migrations


class Migration(migrations.Migration):
    """Drop the dead columns left by migration 0015.

    Migration 0015 removed the workflow and workflow-stage models and the
    fields below from Django state, but its database half only dropped the
    foreign-key constraints. The columns survived on `posthog_task` and
    `posthog_task_run` with no code path that can reach them. This migration
    drops them.

    `task_run_team_stage_task_idx` on `posthog_task_run` is left in place on
    purpose: it backs the optional stage filter and waits on traffic.

    Each table is altered in one statement, so each takes its ACCESS
    EXCLUSIVE lock once instead of once per column. Both statements run in
    one transaction, so `posthog_task` keeps its lock until commit, which
    spans the `posthog_task_run` drop. Each drop is a catalog-only change
    that completes quickly once it holds the lock. The columns were removed
    from state ten months before this drop, so no deploy still reads them.
    """

    dependencies = [
        ("tasks", "0109_drop_orphaned_task_run_stage_index"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE posthog_task
                    DROP COLUMN IF EXISTS github_branch,
                    DROP COLUMN IF EXISTS github_pr_url,
                    DROP COLUMN IF EXISTS position,
                    DROP COLUMN IF EXISTS repository_config,
                    DROP COLUMN IF EXISTS current_stage_id,
                    DROP COLUMN IF EXISTS workflow_id;
                ALTER TABLE posthog_task_run
                    DROP COLUMN IF EXISTS current_stage_id;
            """,
            reverse_sql="""
                ALTER TABLE posthog_task
                    ADD COLUMN IF NOT EXISTS github_branch varchar(255),
                    ADD COLUMN IF NOT EXISTS github_pr_url varchar(200),
                    ADD COLUMN IF NOT EXISTS position integer,
                    ADD COLUMN IF NOT EXISTS repository_config jsonb,
                    ADD COLUMN IF NOT EXISTS current_stage_id uuid,
                    ADD COLUMN IF NOT EXISTS workflow_id uuid;
                ALTER TABLE posthog_task_run
                    ADD COLUMN IF NOT EXISTS current_stage_id uuid;
            """,
        ),
    ]
