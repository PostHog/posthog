# Generated manually for logs sampling rules

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("logs", "0008_logsalertevent_logs_alert_event_alert_ts_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="LogsSamplingRule",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("enabled", models.BooleanField(default=False)),
                (
                    "priority",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Lower values run first; first matching rule wins.",
                    ),
                ),
                (
                    "rule_type",
                    models.CharField(
                        choices=[
                            ("severity_sampling", "Severity sampling"),
                            ("path_drop", "Path drop"),
                            ("rate_limit", "Rate limit"),
                        ],
                        max_length=32,
                    ),
                ),
                ("scope_service", models.CharField(blank=True, max_length=512, null=True)),
                ("scope_path_pattern", models.CharField(blank=True, max_length=1024, null=True)),
                ("scope_attribute_filters", models.JSONField(default=list)),
                ("config", models.JSONField(default=dict)),
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
            options={
                "db_table": "logs_logssamplingrule",
            },
        ),
        migrations.AddIndex(
            model_name="logssamplingrule",
            index=models.Index(fields=["team_id", "enabled", "priority"], name="logs_sampling_team_en_pr_idx"),
        ),
    ]
