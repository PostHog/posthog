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
