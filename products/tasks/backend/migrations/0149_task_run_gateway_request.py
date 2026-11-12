import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1425_workload_trust_policy_request"),
        ("tasks", "0148_task_source_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskRunGatewayRequest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("task_run_id", models.UUIDField()),
                ("request_id", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
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
                "db_table": "posthog_task_run_gateway_request",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("task_run_id", "request_id"), name="task_run_gateway_request_unique"
                    )
                ],
                "indexes": [models.Index(fields=["task_run_id", "created_at"], name="task_run_gw_request_idx")],
            },
        ),
    ]
