import uuid

import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1166_oauth_impersonated_by"),
        ("tasks", "0036_taskrun_output_pr_url_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="CodeWorkflowConfig",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("version", models.PositiveIntegerField(default=1)),
                ("bindings", models.JSONField(default=dict, help_text="Situation id → ordered WorkflowAction list")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="posthog.team"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={
                "db_table": "posthog_code_workflow_config",
            },
        ),
        migrations.CreateModel(
            name="CodePrSnapshot",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("pr_url", models.CharField(max_length=500)),
                ("number", models.PositiveIntegerField()),
                ("title", models.TextField(blank=True, default="")),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("draft", "Draft"),
                            ("merged", "Merged"),
                            ("closed", "Closed"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "ci_status",
                    models.CharField(
                        choices=[
                            ("passing", "Passing"),
                            ("failing", "Failing"),
                            ("pending", "Pending"),
                            ("none", "None"),
                        ],
                        default="none",
                        max_length=10,
                    ),
                ),
                (
                    "review_decision",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("approved", "Approved"),
                            ("changes_requested", "Changes requested"),
                            ("review_required", "Review required"),
                        ],
                        max_length=20,
                        null=True,
                    ),
                ),
                ("unresolved_threads", models.PositiveIntegerField(default=0)),
                ("mergeable", models.BooleanField(blank=True, null=True)),
                ("author_login", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "requested_reviewer_logins",
                    models.JSONField(default=list, help_text="GitHub logins requested as reviewers"),
                ),
                (
                    "pr_updated_at",
                    models.DateTimeField(blank=True, help_text="PR's last-updated time on GitHub", null=True),
                ),
                (
                    "fingerprint",
                    models.CharField(blank=True, default="", help_text="Change-detection hash", max_length=64),
                ),
                (
                    "fetched_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, help_text="When this snapshot was last polled"
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="posthog.team"),
                ),
                (
                    "github_integration",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="posthog.integration",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_code_pr_snapshot",
            },
        ),
        migrations.CreateModel(
            name="CodeWorkstream",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                (
                    "key",
                    models.CharField(
                        help_text="Grouping key: pr:<url> | branch:<repo>#<branch> | path:<path>", max_length=600
                    ),
                ),
                ("repo_name", models.CharField(blank=True, max_length=255, null=True)),
                ("repo_full_path", models.CharField(blank=True, max_length=512, null=True)),
                ("branch", models.CharField(blank=True, max_length=255, null=True)),
                ("pr_url", models.CharField(blank=True, max_length=500, null=True)),
                ("pr", models.JSONField(blank=True, help_text="Per-user-resolved PrSnapshot wire shape", null=True)),
                (
                    "situations",
                    models.JSONField(default=list, help_text="List of situation ids this workstream is in"),
                ),
                (
                    "primary_situation",
                    models.CharField(blank=True, help_text="Board column placement", max_length=20, null=True),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[("attention", "Needs attention"), ("in_progress", "In progress")], max_length=20
                    ),
                ),
                ("tasks", models.JSONField(default=list, help_text="List of {id, title, status} for grouped tasks")),
                ("last_activity_at", models.DateTimeField()),
                (
                    "generated_at",
                    models.DateTimeField(default=django.utils.timezone.now, help_text="When this row was last rebuilt"),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="posthog.team"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "pr_snapshot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="tasks.codeprsnapshot",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_code_workstream",
                "ordering": ["-last_activity_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="codeworkflowconfig",
            constraint=models.UniqueConstraint(fields=("team", "user"), name="code_workflow_config_team_user_unique"),
        ),
        migrations.AddConstraint(
            model_name="codeprsnapshot",
            constraint=models.UniqueConstraint(fields=("team", "pr_url"), name="code_pr_snapshot_team_url_unique"),
        ),
        migrations.AddConstraint(
            model_name="codeworkstream",
            constraint=models.UniqueConstraint(
                fields=("team", "user", "key"), name="code_workstream_team_user_key_unique"
            ),
        ),
        migrations.AddIndex(
            model_name="codeworkstream",
            index=models.Index(fields=["team", "user", "state"], name="code_workstream_state_idx"),
        ),
    ]
