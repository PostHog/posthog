import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1129_userintegration"),
        ("workflows", "0005_remove_hogflowbatchjob_scheduled_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamWorkflowsConfig",
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
                ("capture_engagement_events", models.BooleanField(default=False)),
            ],
        ),
    ]
