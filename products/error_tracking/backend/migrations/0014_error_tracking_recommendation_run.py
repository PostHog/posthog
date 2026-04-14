import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0013_spike_events"),
    ]

    operations = [
        migrations.CreateModel(
            name="ErrorTrackingRecommendationRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "type",
                    models.CharField(choices=[("cross_sell", "Cross sell")], max_length=64),
                ),
                ("meta", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="error_tracking_recommendations",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_errortrackingrecommendationrun",
                "indexes": [
                    models.Index(fields=["team_id"], name="posthog_err_team_id_recomm_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team", "type"),
                        name="unique_error_tracking_recommendation_per_team_type",
                    ),
                ],
            },
        ),
    ]
