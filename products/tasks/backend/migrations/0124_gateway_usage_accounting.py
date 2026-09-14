import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [("tasks", "0123_alter_sandboxsnapshot_integration")]

    operations = [
        migrations.CreateModel(
            name="GatewayUsageCredential",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("bearer_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "task_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gateway_usage_credentials",
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
            options={"db_table": "posthog_task_gateway_usage_credential"},
        ),
        migrations.AddConstraint(
            model_name="gatewayusagecredential",
            constraint=models.UniqueConstraint(
                fields=("task_run", "bearer_hash"), name="task_gateway_usage_credential_unique"
            ),
        ),
        migrations.CreateModel(
            name="GatewayUsageEpoch",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("epoch_id", models.UUIDField()),
                ("sealed_at", models.DateTimeField(blank=True, null=True)),
                ("interrupted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "task_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gateway_usage_epochs",
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
            options={"db_table": "posthog_task_gateway_usage_epoch"},
        ),
        migrations.AddConstraint(
            model_name="gatewayusageepoch",
            constraint=models.UniqueConstraint(fields=("task_run", "epoch_id"), name="task_gateway_usage_epoch_unique"),
        ),
        migrations.CreateModel(
            name="GatewayUsageRequest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("attempt_id", models.UUIDField()),
                ("gateway_request_id", models.CharField(blank=True, max_length=255, null=True)),
                ("cost_microusd", models.PositiveBigIntegerField(blank=True, null=True)),
                ("model", models.CharField(blank=True, max_length=255)),
                ("provider", models.CharField(blank=True, max_length=255)),
                ("input_tokens", models.PositiveBigIntegerField(blank=True, null=True)),
                ("output_tokens", models.PositiveBigIntegerField(blank=True, null=True)),
                ("cache_read_tokens", models.PositiveBigIntegerField(blank=True, null=True)),
                ("cache_write_tokens", models.PositiveBigIntegerField(blank=True, null=True)),
                ("settled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "epoch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="requests",
                        to="tasks.gatewayusageepoch",
                    ),
                ),
                (
                    "task_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gateway_usage_requests",
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
            options={"db_table": "posthog_task_gateway_usage_request"},
        ),
        migrations.AddConstraint(
            model_name="gatewayusagerequest",
            constraint=models.UniqueConstraint(
                fields=("epoch", "attempt_id"), name="task_gateway_usage_request_intent_unique"
            ),
        ),
        migrations.AddIndex(
            model_name="gatewayusagerequest",
            index=models.Index(fields=["task_run", "gateway_request_id"], name="task_gateway_usage_request_idx"),
        ),
    ]
