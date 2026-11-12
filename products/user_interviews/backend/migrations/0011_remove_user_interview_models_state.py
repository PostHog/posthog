from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("user_interviews", "0010_alter_intervieweecontext_team_and_more"),
        ("posthog", "1436_sharingconfiguration_untrack_interviewee_context"),
    ]

    operations = [
        # The tables stay until a later SafeDropTable. Django can no longer cascade a delete into
        # models it cannot see, so drop their foreign keys now, one per operation.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="UserInterview"),
                migrations.DeleteModel(name="IntervieweeContext"),
                migrations.DeleteModel(name="UserInterviewTopic"),
            ],
            database_operations=[
                DropForeignKey("user_interviews_userinterview", column="team_id"),
                DropForeignKey("user_interviews_userinterview", column="created_by_id"),
                DropForeignKey("user_interviews_userinterview", column="topic_id"),
                DropForeignKey("user_interviews_intervieweecontext", column="team_id"),
                DropForeignKey("user_interviews_intervieweecontext", column="created_by_id"),
                DropForeignKey("user_interviews_intervieweecontext", column="topic_id"),
                DropForeignKey("user_interviews_userinterviewtopic", column="team_id"),
                DropForeignKey("user_interviews_userinterviewtopic", column="created_by_id"),
            ],
        ),
    ]
