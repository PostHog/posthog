from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0160_agent_egress_sandbox_binding"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="log_format",
            field=models.CharField(
                choices=[("single", "Single"), ("chunked", "Chunked")],
                db_default="single",
                default="single",
                max_length=16,
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="taskrun",
                    name="log_chunk_count",
                    field=models.PositiveIntegerField(db_default=0, default=0),
                ),
            ],
            database_operations=[
                migrations.AddField(
                    model_name="taskrun",
                    name="log_chunk_count",
                    field=models.IntegerField(db_default=0, default=0),
                ),
                AddConstraintNotValid(
                    model_name="taskrun",
                    constraint=models.CheckConstraint(
                        condition=models.Q(log_chunk_count__gte=0),
                        name="posthog_task_run_log_chunk_count_check",
                    ),
                ),
            ],
        ),
    ]
