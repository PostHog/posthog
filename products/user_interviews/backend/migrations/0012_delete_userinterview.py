from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take UserInterview out of Django's state. The table stays until a later drop."""

    # Each DropForeignKey commits in a transaction of its own, so one drop locks one parent and
    # the child. One lock phase on posthog_team and posthog_user together can fail every retry
    # under load. A retry skips the keys that a failed run already dropped, because DropForeignKey
    # reads what is left from pg_constraint.
    atomic = False

    dependencies = [
        ("user_interviews", "0011_delete_intervieweecontext"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="UserInterview"),
            ],
            database_operations=[
                DropForeignKey("user_interviews_userinterview", column="created_by_id"),
                DropForeignKey("user_interviews_userinterview", column="team_id"),
                DropForeignKey("user_interviews_userinterview", column="topic_id"),
            ],
        ),
    ]
