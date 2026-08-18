from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0094_task_last_activity_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="ci_follow_up_enabled",
            field=models.BooleanField(
                default=True,
                db_default=True,
                help_text=(
                    "If false, the agent does not wake to push follow-up commits to the task's pull request "
                    "after CI failures or review feedback. Lets a user stop automatic changes to their PR."
                ),
            ),
        ),
    ]
