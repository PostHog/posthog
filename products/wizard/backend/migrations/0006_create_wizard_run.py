import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1319_team_posthog_team_widget_token_idx"),
        ("wizard", "0005_wizardsession_handoff_text"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WizardRun",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("environment", models.CharField(choices=[("local", "local"), ("cloud", "cloud")], max_length=20)),
                (
                    "workspace_type",
                    models.CharField(
                        choices=[("local_folder", "local_folder"), ("git_repository", "git_repository")],
                        max_length=30,
                    ),
                ),
                ("workspace", models.JSONField()),
                ("program", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("created", "created"),
                            ("running", "running"),
                            ("completed", "completed"),
                            ("failed", "failed"),
                            ("cancelled", "cancelled"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "error_code",
                    models.CharField(
                        blank=True,
                        max_length=50,
                        null=True,
                    ),
                ),
                ("idempotency_key", models.CharField(blank=True, max_length=255, null=True)),
                ("request_fingerprint", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "dispatch_status",
                    models.CharField(
                        blank=True,
                        choices=[("pending", "pending"), ("dispatched", "dispatched")],
                        max_length=20,
                        null=True,
                    ),
                ),
                ("dispatch_attempts", models.PositiveSmallIntegerField(default=0)),
                ("dispatch_error", models.CharField(blank=True, max_length=255, null=True)),
                ("dispatch_next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("workflow_id", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "stage",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("dispatching", "dispatching"),
                            ("provisioning", "provisioning"),
                            ("preparing_workspace", "preparing_workspace"),
                            ("executing_wizard", "executing_wizard"),
                            ("creating_artifacts", "creating_artifacts"),
                        ],
                        max_length=30,
                        null=True,
                    ),
                ),
                ("stage_started_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.CharField(blank=True, max_length=255, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("deadline_at", models.DateTimeField(blank=True, null=True)),
                ("cancellation_requested_at", models.DateTimeField(blank=True, null=True)),
                ("cancellation_dispatched_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "abstract": False,
                "indexes": [
                    models.Index(
                        fields=["dispatch_next_attempt_at", "created_at"],
                        condition=models.Q(status="created", dispatch_status="pending"),
                        name="wizard_run_dispatch_idx",
                    ),
                    models.Index(
                        fields=["id"],
                        condition=models.Q(
                            status__in=("cancelled", "failed"),
                            cancellation_requested_at__isnull=False,
                            cancellation_dispatched_at__isnull=True,
                        ),
                        name="wizard_run_cancel_idx",
                    ),
                    models.Index(
                        fields=["deadline_at"],
                        condition=models.Q(status__in=("created", "running"), deadline_at__isnull=False),
                        name="wizard_run_deadline_idx",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="wizardrun",
            constraint=models.UniqueConstraint(
                condition=models.Q(("idempotency_key__isnull", False)),
                fields=("team", "idempotency_key"),
                name="unique_wizard_run_idempotency_key_per_team",
            ),
        ),
    ]
