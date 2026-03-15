import django.db.models.deletion
import django.contrib.postgres.fields
import django.contrib.postgres.indexes
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1043_add_15_minute_interval_to_batch_exports"),
        ("llm_analytics", "0020_scoredefinition"),
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
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, blank=True, null=True)),
                ("deleted", models.BooleanField(blank=True, default=False, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("trace_id", models.CharField(max_length=255)),
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
                ("comment", models.TextField(blank=True, null=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "ordering": ["-updated_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="TraceReviewScore",
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
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, blank=True, null=True)),
                (
                    "categorical_values",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=128),
                        blank=True,
                        null=True,
                        size=None,
                    ),
                ),
                ("numeric_value", models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ("boolean_value", models.BooleanField(blank=True, null=True)),
                ("definition_version", models.UUIDField()),
                ("definition_version_number", models.PositiveIntegerField()),
                ("definition_config", models.JSONField(default=dict)),
                (
                    "definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="trace_review_scores",
                        to="llm_analytics.scoredefinition",
                    ),
                ),
                (
                    "review",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scores",
                        to="llm_analytics.tracereview",
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "ordering": ["definition__name", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="tracereview",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted", False)),
                fields=("team", "trace_id"),
                name="llma_tr_rev_active_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="tracereviewscore",
            constraint=models.UniqueConstraint(
                fields=("review", "definition"),
                name="llma_tr_score_def_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="tracereviewscore",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(
                        models.Q(
                            ("categorical_values__isnull", False),
                            ("numeric_value__isnull", True),
                            ("boolean_value__isnull", True),
                        ),
                        models.Q(
                            ("categorical_values__isnull", True),
                            ("numeric_value__isnull", False),
                            ("boolean_value__isnull", True),
                        ),
                        models.Q(
                            ("categorical_values__isnull", True),
                            ("numeric_value__isnull", True),
                            ("boolean_value__isnull", False),
                        ),
                        _connector="OR",
                    )
                ),
                name="llma_tr_score_one_chk",
            ),
        ),
        migrations.AddIndex(
            model_name="tracereview",
            index=models.Index(fields=["team", "trace_id"], name="llma_tr_rev_trace_idx"),
        ),
        migrations.AddIndex(
            model_name="tracereview",
            index=models.Index(fields=["team", "-updated_at", "id"], name="llma_tr_rev_upd_idx"),
        ),
        migrations.AddIndex(
            model_name="tracereviewscore",
            index=models.Index(fields=["team", "definition"], name="llma_tr_score_def_idx"),
        ),
        migrations.AddIndex(
            model_name="tracereviewscore",
            index=models.Index(fields=["team", "review"], name="llma_tr_score_rev_idx"),
        ),
        migrations.AddIndex(
            model_name="tracereviewscore",
            index=django.contrib.postgres.indexes.GinIndex(fields=["categorical_values"], name="llma_tr_score_cat_gin"),
        ),
    ]
