from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_interviews", "0005_remove_userinterviewtopic_interviewee_cohort_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="userinterviewtopic",
            name="invite_subject",
            field=models.CharField(blank=True, db_default="", default="", max_length=255),
        ),
        migrations.AddField(
            model_name="userinterviewtopic",
            name="invite_message",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
    ]
