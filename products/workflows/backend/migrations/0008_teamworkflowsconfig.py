import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1178_datadeletionrequest_person_properties"),
        ("workflows", "0007_migrate_hog_flow_models"),
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
                ("capture_workflows_engagement_events", models.BooleanField(default=False)),
            ],
        ),
    ]
