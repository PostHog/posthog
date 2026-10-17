from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0133_task_comment_activity_optional_task"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamtasksconfig",
            name="agent_instructions",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="usertasksconfig",
            name="agent_instructions",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
    ]
