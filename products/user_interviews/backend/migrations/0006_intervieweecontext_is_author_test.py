from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_interviews", "0005_remove_userinterviewtopic_interviewee_cohort_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="intervieweecontext",
            name="is_author_test",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True for the synthetic context row that lets the topic author dogfood the "
                    "voice interview without consuming a real interviewee slot. Exactly one such "
                    "row exists per topic, distinct from the targeting arrays."
                ),
            ),
        ),
    ]
