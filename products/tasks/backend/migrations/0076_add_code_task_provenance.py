from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0075_task_pin"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="created_via_code",
            field=models.BooleanField(
                editable=False,
                help_text="Whether the current cloud execution was initiated by a PostHog Code OAuth application",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="sandboxsession",
            name="created_via_code",
            field=models.BooleanField(
                editable=False,
                help_text="PostHog Code OAuth provenance at provision time",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="sandboxsession",
            name="loop_internal",
            field=models.BooleanField(
                editable=False,
                help_text="Loop internal classification at provision time",
                null=True,
            ),
        ),
    ]
