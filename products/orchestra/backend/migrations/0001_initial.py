import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Execution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("execution_id", models.TextField(db_index=True)),
                ("run_id", models.UUIDField(default=uuid.uuid4)),
                ("execution_type", models.TextField()),
                ("step_queue", models.TextField(default="default")),
                ("input", models.JSONField(null=True)),
                ("status", models.TextField(default="RUNNING")),
                ("result", models.JSONField(null=True)),
                ("error", models.JSONField(null=True)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(null=True)),
            ],
            options={
                "unique_together": {("execution_id", "run_id")},
            },
        ),
        migrations.CreateModel(
            name="Task",
            fields=[
                ("task_id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ("task_queue", models.TextField()),
                ("task_type", models.TextField()),
                ("execution_id", models.TextField()),
                ("run_id", models.UUIDField()),
                ("scheduled_event_id", models.BigIntegerField(null=True)),
                ("step_type", models.TextField(null=True)),
                ("input", models.JSONField(null=True)),
                ("visible_at", models.DateTimeField(auto_now_add=True)),
                ("locked_by", models.TextField(null=True)),
                ("locked_until", models.DateTimeField(null=True)),
                ("attempt", models.IntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        condition=models.Q(("locked_until__isnull", True)),
                        fields=["task_queue", "visible_at"],
                        name="idx_orch_tasks_poll",
                    ),
                    models.Index(
                        condition=models.Q(("locked_until__isnull", False)),
                        fields=["task_queue", "locked_until"],
                        name="idx_orch_tasks_lease",
                    ),
                ],
            },
        ),
        migrations.RunSQL(
            sql="""
                CREATE TABLE orchestra_event (
                    execution_id   TEXT        NOT NULL,
                    run_id         UUID        NOT NULL,
                    event_id       BIGINT      NOT NULL,
                    event_type     TEXT        NOT NULL,
                    "timestamp"    TIMESTAMPTZ NOT NULL DEFAULT now(),
                    attributes     JSONB       NOT NULL DEFAULT '{}'::jsonb,
                    PRIMARY KEY (execution_id, run_id, event_id)
                ) PARTITION BY HASH (execution_id);

                DO $$
                DECLARE
                    i INT;
                BEGIN
                    FOR i IN 0..3 LOOP
                        EXECUTE format(
                            'CREATE TABLE orchestra_event_p%1$s PARTITION OF orchestra_event '
                            'FOR VALUES WITH (MODULUS 4, REMAINDER %1$s)',
                            i
                        );
                    END LOOP;
                END $$;
            """,
            reverse_sql="""
                DROP TABLE IF EXISTS orchestra_event CASCADE;
            """,
        ),
    ]
