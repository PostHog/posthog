from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0086_clear_disconnected_channel_repositories")]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="awaiting_input_request_id",
            field=models.CharField(
                blank=True,
                default=None,
                help_text="Id of the permission request this run is waiting on, or null when it is not waiting on one.",
                max_length=255,
                null=True,
            ),
        ),
    ]
