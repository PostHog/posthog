import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog_ai", "0001_initial"),
        ("ee", "0043_teamsessionsummariesconfig_custom_tags"),
        ("posthog", "1152_fix_device_bucketing_persist_across_auth"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TrackedQuestion",
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
                ("source_human_message_id", models.UUIDField()),
                ("source_visualization_message_id", models.UUIDField()),
                ("title", models.CharField(max_length=255)),
                ("question_text", models.TextField()),
                ("baseline_summary", models.TextField(blank=True, default="")),
                ("baseline_captured_at", models.DateTimeField()),
                (
                    "cadence",
                    models.CharField(
                        choices=[("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
                        default="weekly",
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("paused", "Paused"), ("archived", "Archived")],
                        default="active",
                        max_length=10,
                    ),
                ),
                ("next_run_at", models.DateTimeField(db_index=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("repository", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tracked_questions",
                        to="posthog.team",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tracked_questions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source_conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tracked_questions",
                        to="ee.conversation",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["team", "status", "next_run_at"], name="ph_ai_tq_due_idx"),
                    models.Index(fields=["team", "source_conversation"], name="ph_ai_tq_team_conv_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="trackedquestion",
            constraint=models.UniqueConstraint(
                fields=("team", "source_conversation", "source_visualization_message_id"),
                name="unique_tracked_question_per_message",
            ),
        ),
        migrations.CreateModel(
            name="TrackedQuestionRun",
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
                    "state",
                    models.CharField(
                        choices=[
                            ("ok", "OK"),
                            ("drifted", "Drifted"),
                            ("error", "Error"),
                            ("skipped", "Skipped"),
                        ],
                        default="ok",
                        max_length=10,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("none", "None"),
                            ("minor", "Minor"),
                            ("moderate", "Moderate"),
                            ("significant", "Significant"),
                        ],
                        default="none",
                        max_length=12,
                    ),
                ),
                ("narrative", models.TextField(blank=True, default="")),
                ("judge_summary", models.TextField(blank=True, default="")),
                ("judge_payload", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True, default="")),
                ("signal_emitted_at", models.DateTimeField(blank=True, null=True)),
                ("signal_source_id", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
                (
                    "tracked_question",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runs",
                        to="posthog_ai.trackedquestion",
                    ),
                ),
                (
                    "forked_conversation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="parent_question_runs",
                        to="ee.conversation",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["tracked_question", "-created_at"],
                        name="ph_ai_tq_run_chrono_idx",
                    ),
                ],
            },
        ),
    ]
