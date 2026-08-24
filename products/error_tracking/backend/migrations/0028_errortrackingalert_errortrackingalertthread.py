import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils

import products.error_tracking.backend.models


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0027_add_severity_rules"),
        ("posthog", "1315_githubinstallrequest_account"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ErrorTrackingAlert",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.TextField()),
                ("enabled", models.BooleanField(default=True)),
                ("triggers", models.JSONField(default=list)),
                (
                    "channel_type",
                    models.TextField(
                        choices=products.error_tracking.backend.models.error_tracking_alert_channel_type_choices
                    ),
                ),
                ("config", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "integration",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="posthog.integration"
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False, on_delete=django.db.models.deletion.CASCADE, to="posthog.team"
                    ),
                ),
            ],
            options={
                "db_table": "posthog_errortrackingalert",
                "indexes": [models.Index(fields=["team", "enabled"], name="idx_et_alert_team_enabled")],
            },
        ),
        migrations.CreateModel(
            name="ErrorTrackingAlertThread",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("external_ref", models.JSONField(blank=True, default=dict)),
                ("delivered_event_uuids", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "alert",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="threads",
                        to="error_tracking.errortrackingalert",
                    ),
                ),
                (
                    "issue",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alert_threads",
                        to="error_tracking.errortrackingissue",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False, on_delete=django.db.models.deletion.CASCADE, to="posthog.team"
                    ),
                ),
            ],
            options={
                "db_table": "posthog_errortrackingalertthread",
                "constraints": [
                    models.UniqueConstraint(fields=("alert", "issue"), name="unique_error_tracking_alert_thread")
                ],
            },
        ),
    ]
