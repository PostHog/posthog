import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0008_teamworkflowsconfig"),
        ("posthog", "1251_alter_integration_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="HogFlowIntegration",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "hog_flow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="integration_links",
                        to="workflows.hogflow",
                    ),
                ),
                (
                    "integration",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hog_flow_links",
                        to="posthog.integration",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="hogflowintegration",
            constraint=models.UniqueConstraint(fields=("hog_flow", "integration"), name="unique_hog_flow_integration"),
        ),
    ]
