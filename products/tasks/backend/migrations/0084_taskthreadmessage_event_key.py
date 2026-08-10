from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0083_taskcommentactivity"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskthreadmessage",
            name="event_key",
            field=models.CharField(blank=True, db_default="", default="", max_length=255),
        ),
    ]
