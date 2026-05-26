import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1178_datadeletionrequest_person_properties"),
        ("workflows", "0006_drop_hogflowbatchjob_scheduled_at_column"),
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
