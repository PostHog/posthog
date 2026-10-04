from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take IntervieweeContext out of Django's state. The table stays until a later drop.

    Django stops cascading into a table it cannot see, so its foreign keys go in the same
    migration. Each table gets its own migration.
    """

    # Each DropForeignKey commits in a transaction of its own, so one drop locks one parent and
    # the child. One lock phase on posthog_team and posthog_user together can fail every retry
    # under load. A retry skips the keys that a failed run already dropped, because DropForeignKey
    # reads what is left from pg_constraint.
    atomic = False

    dependencies = [
        ("posthog", "1392_untrack_sharingconfiguration_interviewee_context"),
        ("user_interviews", "0010_alter_intervieweecontext_team_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="IntervieweeContext"),
            ],
            database_operations=[
                DropForeignKey("user_interviews_intervieweecontext", column="created_by_id"),
                DropForeignKey("user_interviews_intervieweecontext", column="team_id"),
                DropForeignKey("user_interviews_intervieweecontext", column="topic_id"),
            ],
        ),
    ]
