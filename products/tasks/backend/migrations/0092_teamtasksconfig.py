import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1306_add_youtube_analytics_integration_kind"),
        ("tasks", "0091_task_pr_loop_enabled"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamTasksConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                ("pr_loop_enabled", models.BooleanField(blank=True, null=True)),
            ],
        ),
    ]
