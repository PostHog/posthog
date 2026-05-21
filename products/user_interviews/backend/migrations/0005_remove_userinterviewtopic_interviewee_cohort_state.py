"""Phase 1 of 2: remove `UserInterviewTopic.interviewee_cohort` from Django state.

The actual `DROP COLUMN` happens in a follow-up migration once this deploy bakes —
keeping the column in the DB during one deploy cycle lets old workers and rollbacks
keep reading from it without error (the field was nullable, so any reader gets None).

See PostHog's safe-django-migrations playbook (docs/published/handbook/engineering/
safe-django-migrations.md#dropping-columns) for the two-phase pattern.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("user_interviews", "0004_userinterview_vapi_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="userinterviewtopic",
                    name="interviewee_cohort",
                ),
            ],
            database_operations=[],
        ),
    ]
