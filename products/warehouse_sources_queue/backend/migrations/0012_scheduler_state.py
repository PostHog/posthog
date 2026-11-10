from django.db import migrations, models


def _create_scheduler_tables(apps, schema_editor):
    # One statement per execute(): psycopg3 uses the extended query protocol,
    # which parses a single statement at a time.
    schema_editor.execute("""
        CREATE TABLE queueschedulerstate (
            id BIGSERIAL PRIMARY KEY,
            kind VARCHAR(100) NOT NULL,
            schedule_key VARCHAR(200) NOT NULL,
            team_id BIGINT NOT NULL,
            interval_seconds BIGINT NOT NULL,
            offset_seconds INT NOT NULL,
            next_due_at TIMESTAMPTZ NOT NULL,
            refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT qss_kind_key_uniq UNIQUE (kind, schedule_key)
        )
    """)
    schema_editor.execute("""
        CREATE INDEX qss_next_due_idx ON queueschedulerstate (next_due_at)
    """)
    schema_editor.execute("""
        CREATE INDEX qss_refreshed_idx ON queueschedulerstate (refreshed_at)
    """)
    schema_editor.execute("""
        CREATE TABLE queueschedulerdecision (
            id BIGSERIAL PRIMARY KEY,
            team_id BIGINT NOT NULL,
            kind VARCHAR(100) NOT NULL,
            schedule_key VARCHAR(200) NOT NULL,
            window_boundary TIMESTAMPTZ NOT NULL,
            due_at TIMESTAMPTZ NOT NULL,
            decision VARCHAR(32) NOT NULL,
            interval_seconds BIGINT NOT NULL,
            late_seconds DOUBLE PRECISION NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT qsd_kind_key_due_uniq UNIQUE (kind, schedule_key, due_at)
        )
    """)
    schema_editor.execute("""
        CREATE INDEX qsd_observed_at_idx ON queueschedulerdecision (observed_at)
    """)


def _drop_scheduler_tables(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS queueschedulerdecision CASCADE")
    schema_editor.execute("DROP TABLE IF EXISTS queueschedulerstate CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0011_generic_job_tables"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="QueueSchedulerState",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                            ),
                        ),
                        ("kind", models.CharField(max_length=100)),
                        ("schedule_key", models.CharField(max_length=200)),
                        ("team_id", models.BigIntegerField()),
                        ("interval_seconds", models.BigIntegerField()),
                        ("offset_seconds", models.IntegerField()),
                        ("next_due_at", models.DateTimeField()),
                        ("refreshed_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "db_table": "queueschedulerstate",
                        "constraints": [
                            models.UniqueConstraint(fields=("kind", "schedule_key"), name="qss_kind_key_uniq")
                        ],
                        "indexes": [
                            models.Index(fields=["next_due_at"], name="qss_next_due_idx"),
                            models.Index(fields=["refreshed_at"], name="qss_refreshed_idx"),
                        ],
                    },
                ),
                migrations.CreateModel(
                    name="QueueSchedulerDecision",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                            ),
                        ),
                        ("team_id", models.BigIntegerField()),
                        ("kind", models.CharField(max_length=100)),
                        ("schedule_key", models.CharField(max_length=200)),
                        ("window_boundary", models.DateTimeField()),
                        ("due_at", models.DateTimeField()),
                        ("decision", models.CharField(max_length=32)),
                        ("interval_seconds", models.BigIntegerField()),
                        ("late_seconds", models.FloatField()),
                        ("observed_at", models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        "db_table": "queueschedulerdecision",
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("kind", "schedule_key", "due_at"), name="qsd_kind_key_due_uniq"
                            )
                        ],
                        "indexes": [models.Index(fields=["observed_at"], name="qsd_observed_at_idx")],
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(_create_scheduler_tables, _drop_scheduler_tables),
    ]
