from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take UserInterviewTopic out of Django's state. The table stays until a later drop."""

    dependencies = [
        ("user_interviews", "0012_delete_userinterview"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="UserInterviewTopic"),
            ],
            database_operations=[
                DropForeignKey(
                    "user_interviews_userinterviewtopic",
                    column=["created_by_id", "team_id"],
                ),
            ],
        ),
    ]
