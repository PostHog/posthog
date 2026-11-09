from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey",
            name="repeat_until_stopped",
            field=models.BooleanField(
                default=False,
                help_text="For a recurring schedule, keep repeating every iteration_frequency_days until the survey is stopped. When true, iteration_count is ignored and the survey never closes on its own after a final repeat.",
                null=True,
            ),
        ),
    ]
