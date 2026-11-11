from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0134_team_and_user_agent_instructions"),
    ]

    operations = [
        migrations.AddField(
            model_name="usertasksconfig",
            name="task_defaults",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
