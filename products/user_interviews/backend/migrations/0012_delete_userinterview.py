from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take UserInterview out of Django's state. The table stays until a later drop."""

    dependencies = [
        ("user_interviews", "0011_delete_intervieweecontext"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="UserInterview"),
            ],
            database_operations=[
                DropForeignKey(
                    "user_interviews_userinterview",
                    column=["created_by_id", "team_id", "topic_id"],
                ),
            ],
        ),
    ]
