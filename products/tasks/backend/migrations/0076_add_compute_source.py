from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0075_task_pin"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="compute_source",
            field=models.CharField(
                choices=[("posthog_desktop", "PostHog Desktop")],
                editable=False,
                help_text="Trusted surface that initiated the current cloud execution",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="sandboxsession",
            name="compute_source",
            field=models.CharField(
                choices=[("posthog_desktop", "PostHog Desktop")],
                editable=False,
                help_text="Trusted compute source at provision or claim time",
                max_length=32,
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
