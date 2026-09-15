from django.db import migrations


class Migration(migrations.Migration):
    """Drop the Code Home tables 0069 left behind.

    0069 took CodeWorkstream, CodePrSnapshot and CodeWorkflowConfig out of Django state and kept
    their tables for one deploy cycle. It names a follow-up RunSQL migration to drop them that
    never landed, so the tables still hold repository paths, pull request snapshots and workflow
    configuration, and still carry foreign keys to posthog_team, posthog_user and
    posthog_integration.

    Dropping only those keys would be worse than leaving them. A team delete fails at COMMIT
    today, because the constraints are DEFERRABLE INITIALLY DEFERRED with NO ACTION and Django no
    longer cascades into a relation it cannot see. Take the keys away on their own and the delete
    succeeds while the rows survive, so a deleted tenant leaves its data behind with nothing
    pointing at it. The user keys are worse still, because the pre-delete cleanup in
    posthog/models/team/util.py is keyed on team_id and would never reach them.

    DROP TABLE takes ACCESS EXCLUSIVE on every table these foreign keys reference, and two of
    those are hot. The statement runs under a short lock_timeout so it fails fast and bin/migrate
    retries, rather than queueing that lock for the whole MIGRATE_LOCK_TIMEOUT window while every
    query arriving behind it waits.
    """

    dependencies = [
        ("tasks", "0123_alter_sandboxsnapshot_integration"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                SET LOCAL lock_timeout = '2s';
                DROP TABLE IF EXISTS posthog_code_workstream, posthog_code_pr_snapshot, posthog_code_workflow_config;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
