import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1039_subscription_dashboard_export_insights"),
        ("llm_analytics", "0018_migrate_clustering_configs_to_jobs"),
    ]

    operations = [
        migrations.CreateModel(
            name="TraceReview",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True, blank=True)),
                ("deleted", models.BooleanField(blank=True, default=False, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("trace_id", models.CharField(max_length=255)),
                (
                    "score_kind",
                    models.CharField(
                        blank=True,
                        choices=[("label", "label"), ("numeric", "numeric")],
                        max_length=32,
                        null=True,
                    ),
                ),
                (
                    "score_label",
                    models.CharField(
                        blank=True,
                        choices=[("good", "good"), ("bad", "bad")],
                        max_length=32,
                        null=True,
                    ),
                ),
                ("score_numeric", models.DecimalField(blank=True, decimal_places=3, max_digits=8, null=True)),
                ("comment", models.TextField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="posthog.user",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="tracereview",
            index=models.Index(fields=["team", "trace_id"], name="llma_trace_review_team_trace_idx"),
        ),
        migrations.AddIndex(
            model_name="tracereview",
            index=models.Index(fields=["team", "-updated_at", "id"], name="llma_trace_review_team_updated_idx"),
        ),
        migrations.AddIndex(
            model_name="tracereview",
            index=models.Index(fields=["team", "score_kind", "score_label"], name="llma_trace_review_team_score_idx"),
        ),
        migrations.AddConstraint(
            model_name="tracereview",
            constraint=models.UniqueConstraint(
                condition=models.Q(deleted=False),
                fields=("team", "trace_id"),
                name="uniq_active_llma_trace_review_per_team",
            ),
        ),
    ]
