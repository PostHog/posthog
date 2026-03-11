import django.db.models.deletion
import django.contrib.postgres.fields
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1043_add_15_minute_interval_to_batch_exports"),
        ("llm_analytics", "0018_migrate_clustering_configs_to_jobs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EvaluationReport",
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
                (
                    "frequency",
                    models.CharField(
                        choices=[("hourly", "Hourly"), ("daily", "Daily"), ("weekly", "Weekly")],
                        max_length=10,
                    ),
                ),
                (
                    "byweekday",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(
                            choices=[
                                ("monday", "Monday"),
                                ("tuesday", "Tuesday"),
                                ("wednesday", "Wednesday"),
                                ("thursday", "Thursday"),
                                ("friday", "Friday"),
                                ("saturday", "Saturday"),
                                ("sunday", "Sunday"),
                            ],
                            max_length=10,
                        ),
                        blank=True,
                        default=None,
                        null=True,
                        size=None,
                    ),
                ),
                ("start_date", models.DateTimeField()),
                ("next_delivery_date", models.DateTimeField(blank=True, null=True)),
                ("delivery_targets", models.JSONField(default=list)),
                ("max_sample_size", models.IntegerField(default=200)),
                ("enabled", models.BooleanField(default=True)),
                ("deleted", models.BooleanField(default=False)),
                ("last_delivered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
                (
                    "evaluation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports",
                        to="llm_analytics.evaluation",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="evaluationreport",
            index=models.Index(
                fields=["team", "-created_at", "id"],
                name="llm_analyti_team_id_eval_rpt_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="evaluationreport",
            index=models.Index(
                fields=["next_delivery_date", "enabled", "deleted"],
                name="llm_analyti_ndd_enabled_del_idx",
            ),
        ),
        migrations.CreateModel(
            name="EvaluationReportRun",
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
                ("content", models.JSONField(default=dict)),
                ("metadata", models.JSONField(default=dict)),
                ("period_start", models.DateTimeField()),
                ("period_end", models.DateTimeField()),
                (
                    "delivery_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("delivered", "Delivered"),
                            ("partial_failure", "Partial Failure"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("delivery_errors", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runs",
                        to="llm_analytics.evaluationreport",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="evaluationreportrun",
            index=models.Index(
                fields=["report", "-created_at"],
                name="llm_analyti_rpt_run_created_idx",
            ),
        ),
    ]
