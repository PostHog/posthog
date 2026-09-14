from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Drop the seven foreign keys on the retired Code Home tables, which nothing owns any more.

    0069 took CodeWorkstream, CodePrSnapshot and CodeWorkflowConfig out of Django state and
    left their tables for one deploy cycle. It names a follow-up RunSQL migration to drop the
    tables. That follow-up never landed, so the tables still carry every foreign key they had.

    A parent delete stops cascading into a relation Django cannot see. The constraints are
    DEFERRABLE INITIALLY DEFERRED with NO ACTION, so a team delete finishes its whole cascade
    and Postgres then rejects the transaction at COMMIT.

    The tables stay, so dropping them remains a separate decision. Only the constraints go.
    """

    dependencies = [
        ("tasks", "0123_alter_sandboxsnapshot_integration"),
    ]

    operations = [
        DropForeignKey("posthog_code_pr_snapshot", column="team_id"),
        DropForeignKey("posthog_code_pr_snapshot", column="github_integration_id"),
        DropForeignKey("posthog_code_workflow_config", column="team_id"),
        DropForeignKey("posthog_code_workflow_config", column="user_id"),
        DropForeignKey("posthog_code_workstream", column="team_id"),
        DropForeignKey("posthog_code_workstream", column="user_id"),
        DropForeignKey("posthog_code_workstream", column="pr_snapshot_id"),
    ]
