from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0160_agent_egress_sandbox_binding")]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="last_heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrun",
            name="agent_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("starting", "Starting"),
                    ("ready", "Ready"),
                    ("busy", "Busy"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
