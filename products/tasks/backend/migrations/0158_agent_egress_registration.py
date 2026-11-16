import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1433_integrationrepositorycacheentry_activity"),
        ("tasks", "0157_task_pr_outcomes"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentEgressRegistration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("execution_id", models.UUIDField(editable=False, unique=True)),
                ("region", models.CharField(max_length=32)),
                ("actor_id", models.PositiveBigIntegerField()),
                ("actor_epoch", models.PositiveBigIntegerField()),
                ("task_ownership_version", models.TextField(null=True)),
                ("authority", models.CharField(max_length=259)),
                ("relay_key_sha256", models.CharField(max_length=43)),
                ("lease_expires_at", models.DateTimeField()),
                ("revoked", models.BooleanField(default=False)),
                (
                    "task_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="egress_registrations",
                        to="tasks.taskrun",
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
                "db_table": "posthog_agent_egress_registration",
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("revoked", False)),
                        fields=("task_run",),
                        name="agent_egress_active_run_unique",
                    )
                ],
            },
        ),
    ]
