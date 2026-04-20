import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1002_experiment_exposure_preaggregation_enabled"),
        ("llm_analytics", "0013_add_openrouter_provider"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClusteringConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="clustering_config",
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                ("event_filters", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "app_label": "llm_analytics",
            },
        ),
    ]
