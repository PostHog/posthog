import django.db.models.deletion
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [("wizard", "0006_create_wizard_run")]

    operations = [
        migrations.CreateModel(
            name="WizardRunArtifact",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[("git_diff", "git_diff"), ("pull_request", "pull_request")],
                        max_length=30,
                    ),
                ),
                ("storage_path", models.CharField(blank=True, max_length=1024, null=True)),
                ("external_url", models.URLField(blank=True, max_length=1024, null=True)),
                ("metadata", models.JSONField(blank=True, null=True)),
                ("size_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("content_hash", models.CharField(blank=True, max_length=64, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="artifacts",
                        to="wizard.wizardrun",
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
            options={"abstract": False},
        ),
        migrations.AddConstraint(
            model_name="wizardrunartifact",
            constraint=models.UniqueConstraint(
                fields=("run", "type"),
                name="unique_wizard_artifact_type_per_run",
            ),
        ),
    ]
