from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take IntervieweeContext out of Django's state. The table stays until a later drop.

    Django stops cascading into a table it cannot see, so its foreign keys go in the same
    migration. Each table gets its own migration, so each lock phase runs alone.
    """

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
                DropForeignKey(
                    "user_interviews_intervieweecontext",
                    column=["created_by_id", "team_id", "topic_id"],
                ),
            ],
        ),
    ]
