from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0057_channelfeedmessage")]

    operations = [
        migrations.AddField(
            model_name="taskthreadmessage",
            name="author_kind",
            field=models.CharField(
                choices=[("human", "Human"), ("system", "System"), ("agent", "Agent")],
                default="human",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="taskthreadmessage",
            name="event",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="taskthreadmessage",
            name="payload",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
