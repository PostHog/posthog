import datetime

from django.db import migrations, models

from posthog.models.utils import uuid7

# How many daily partitions to pre-create ahead of today.
PARTITIONS_AHEAD = 7


def _create_job_step_table(apps, schema_editor):
    # One statement per execute(): psycopg3 uses the extended query protocol,
    # which parses a single statement at a time.
    schema_editor.execute("""
        CREATE TABLE queuejobstep (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            job_id UUID NOT NULL,
            job_created_at TIMESTAMPTZ NOT NULL,
            step_key VARCHAR(200) NOT NULL,
            state VARCHAR(16) NOT NULL,
            job_attempt SMALLINT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ NOT NULL,
            result JSONB,
            error TEXT,
            PRIMARY KEY (id, job_created_at)
        ) PARTITION BY RANGE (job_created_at)
    """)
    # The table is new and empty, so plain index builds on the parent take no lock that matters.
    # A unique index on a partitioned table must contain the partition key.
    schema_editor.execute("""
        CREATE UNIQUE INDEX qjstep_completed_uniq ON queuejobstep (job_id, job_created_at, step_key)
            WHERE state IN ('succeeded', 'skipped')
    """)
    schema_editor.execute("CREATE INDEX qjstep_job_key_idx ON queuejobstep (job_id, step_key)")
    schema_editor.execute("CREATE TABLE queuejobstep_default PARTITION OF queuejobstep DEFAULT")

    today = datetime.date.today()
    for offset in range(PARTITIONS_AHEAD + 1):
        day = today + datetime.timedelta(days=offset)
        next_day = day + datetime.timedelta(days=1)
        schema_editor.execute(
            f"CREATE TABLE IF NOT EXISTS queuejobstep_{day.strftime('%Y%m%d')} "
            f"PARTITION OF queuejobstep "
            f"FOR VALUES FROM ('{day.isoformat()}') TO ('{next_day.isoformat()}')"
        )


def _drop_job_step_table(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS queuejobstep CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0013_queueschedulerdecision_job_id"),
    ]

    operations = [
        # Django state only: the DDL is RunPython below because Django cannot
        # express PARTITION BY RANGE (same pattern as 0011).
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="QueueJobStep",
                    fields=[
                        ("id", models.UUIDField(default=uuid7, editable=False, primary_key=True, serialize=False)),
                        ("job_id", models.UUIDField()),
                        ("job_created_at", models.DateTimeField()),
                        ("step_key", models.CharField(max_length=200)),
                        (
                            "state",
                            models.CharField(
                                choices=[("succeeded", "succeeded"), ("failed", "failed"), ("skipped", "skipped")],
                                max_length=16,
                            ),
                        ),
                        ("job_attempt", models.SmallIntegerField()),
                        ("started_at", models.DateTimeField()),
                        ("ended_at", models.DateTimeField()),
                        ("result", models.JSONField(blank=True, null=True)),
                        ("error", models.TextField(blank=True, null=True)),
                    ],
                    options={
                        "db_table": "queuejobstep",
                        "constraints": [
                            models.UniqueConstraint(
                                condition=models.Q(state__in=["succeeded", "skipped"]),
                                fields=("job_id", "job_created_at", "step_key"),
                                name="qjstep_completed_uniq",
                            )
                        ],
                        "indexes": [models.Index(fields=["job_id", "step_key"], name="qjstep_job_key_idx")],
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(_create_job_step_table, _drop_job_step_table),
    ]
