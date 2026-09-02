import datetime

from django.db import migrations, models

from posthog.models.utils import uuid7

# How many daily partitions to pre-create ahead of today.
PARTITIONS_AHEAD = 7


def _precreate_daily_partitions(schema_editor, parent_table):
    """Pre-create one daily range partition per day for today + next N days.

    Same shape as 0001: individual ``CREATE TABLE ... PARTITION OF`` statements
    from Python so the DDL applies against Postgres-wire targets without
    PL/pgSQL support.
    """
    today = datetime.date.today()
    for offset in range(PARTITIONS_AHEAD + 1):
        day = today + datetime.timedelta(days=offset)
        next_day = day + datetime.timedelta(days=1)
        suffix = day.strftime("%Y%m%d")
        schema_editor.execute(
            f"CREATE TABLE IF NOT EXISTS {parent_table}_{suffix} "
            f"PARTITION OF {parent_table} "
            f"FOR VALUES FROM ('{day.isoformat()}') TO ('{next_day.isoformat()}')"
        )


def _create_generic_job_tables(apps, schema_editor):
    # One statement per execute(): psycopg3 uses the extended query protocol,
    # which parses a single statement at a time.
    schema_editor.execute("""
        CREATE TABLE queuejob (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            kind VARCHAR(100) NOT NULL,
            lane VARCHAR(16) NOT NULL,
            group_key VARCHAR(400) NOT NULL,
            team_id BIGINT NOT NULL,
            run_id VARCHAR(200),
            sequence INT NOT NULL DEFAULT 0,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            priority SMALLINT NOT NULL DEFAULT 0,
            dedup_key VARCHAR(400),
            latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            latest_attempt SMALLINT NOT NULL DEFAULT 0,
            state_changed_at TIMESTAMPTZ,
            superseded BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)
    # The claim scan and its gates, mirroring the sourcebatch partial-index
    # physics with lane/kind in the predicates so each fleet's poll cost tracks
    # its own claimable set.
    schema_editor.execute("""
        CREATE INDEX qj_claimable_idx ON queuejob (lane, kind, team_id, created_at, sequence)
            WHERE latest_state IN ('pending', 'waiting_retry')
    """)
    schema_editor.execute("""
        CREATE INDEX qj_run_gate_idx ON queuejob (run_id, latest_state, sequence)
            WHERE latest_state IN ('executing', 'waiting_retry', 'failed')
    """)
    schema_editor.execute("""
        CREATE INDEX qj_group_busy_idx ON queuejob (lane, group_key)
            WHERE latest_state = 'executing'
    """)
    schema_editor.execute("""
        CREATE INDEX qj_failed_changed_idx ON queuejob (state_changed_at)
            WHERE latest_state = 'failed'
    """)
    # Dedup lookups. A partitioned table cannot carry a unique index that omits
    # the partition key, so uniqueness of live (kind, dedup_key) pairs is
    # enforced by the insert statement's NOT EXISTS guard; this index makes
    # that guard and the lookup cheap.
    schema_editor.execute("""
        CREATE INDEX qj_dedup_idx ON queuejob (kind, dedup_key)
            WHERE dedup_key IS NOT NULL
    """)
    schema_editor.execute("CREATE TABLE queuejob_default PARTITION OF queuejob DEFAULT")

    schema_editor.execute("""
        CREATE TABLE queuejobstatus (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            job_id UUID NOT NULL,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)
    schema_editor.execute(
        "CREATE INDEX qjs_job_id_desc_state_idx ON queuejobstatus (job_id, created_at DESC, id DESC, job_state)"
    )
    schema_editor.execute("CREATE TABLE queuejobstatus_default PARTITION OF queuejobstatus DEFAULT")

    schema_editor.execute("""
        CREATE TABLE queuejoblease (
            id BIGSERIAL PRIMARY KEY,
            lane VARCHAR(16) NOT NULL,
            group_key VARCHAR(400) NOT NULL,
            owner_token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT qjl_lane_group_uniq UNIQUE (lane, group_key)
        )
    """)
    schema_editor.execute("CREATE INDEX qjl_expires_at_idx ON queuejoblease (expires_at)")

    _precreate_daily_partitions(schema_editor, "queuejob")
    _precreate_daily_partitions(schema_editor, "queuejobstatus")


def _drop_generic_job_tables(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS queuejoblease CASCADE")
    schema_editor.execute("DROP TABLE IF EXISTS queuejobstatus CASCADE")
    schema_editor.execute("DROP TABLE IF EXISTS queuejob CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0009_sourcebatch_job_id_idx"),
    ]

    operations = [
        # Django state only: the DDL is RunPython below because Django cannot
        # express PARTITION BY RANGE (same pattern as 0001).
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="QueueJob",
                    fields=[
                        ("id", models.UUIDField(default=uuid7, editable=False, primary_key=True, serialize=False)),
                        ("kind", models.CharField(max_length=100)),
                        ("lane", models.CharField(max_length=16)),
                        ("group_key", models.CharField(max_length=400)),
                        ("team_id", models.BigIntegerField()),
                        ("run_id", models.CharField(blank=True, max_length=200, null=True)),
                        ("sequence", models.IntegerField(default=0)),
                        ("payload", models.JSONField(blank=True, default=dict)),
                        ("priority", models.SmallIntegerField(default=0)),
                        ("dedup_key", models.CharField(blank=True, max_length=400, null=True)),
                        ("latest_state", models.CharField(default="pending", max_length=32)),
                        ("latest_attempt", models.SmallIntegerField(default=0)),
                        ("state_changed_at", models.DateTimeField(blank=True, null=True)),
                        ("superseded", models.BooleanField(default=False)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        "db_table": "queuejob",
                        "indexes": [
                            models.Index(
                                fields=["lane", "kind", "team_id", "created_at", "sequence"],
                                name="qj_claimable_idx",
                                condition=models.Q(latest_state__in=["pending", "waiting_retry"]),
                            ),
                            models.Index(
                                fields=["run_id", "latest_state", "sequence"],
                                name="qj_run_gate_idx",
                                condition=models.Q(latest_state__in=["executing", "waiting_retry", "failed"]),
                            ),
                            models.Index(
                                fields=["lane", "group_key"],
                                name="qj_group_busy_idx",
                                condition=models.Q(latest_state="executing"),
                            ),
                            models.Index(
                                fields=["state_changed_at"],
                                name="qj_failed_changed_idx",
                                condition=models.Q(latest_state="failed"),
                            ),
                            models.Index(
                                fields=["kind", "dedup_key"],
                                name="qj_dedup_idx",
                                condition=models.Q(dedup_key__isnull=False),
                            ),
                        ],
                    },
                ),
                migrations.CreateModel(
                    name="QueueJobStatus",
                    fields=[
                        ("id", models.UUIDField(default=uuid7, editable=False, primary_key=True, serialize=False)),
                        ("job_id", models.UUIDField()),
                        (
                            "job_state",
                            models.CharField(
                                choices=[
                                    ("waiting", "waiting"),
                                    ("executing", "executing"),
                                    ("succeeded", "succeeded"),
                                    ("waiting_retry", "waiting_retry"),
                                    ("failed", "failed"),
                                ],
                                max_length=32,
                            ),
                        ),
                        ("attempt", models.SmallIntegerField(default=0)),
                        ("exec_time", models.DateTimeField(blank=True, null=True)),
                        ("error_response", models.JSONField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        "db_table": "queuejobstatus",
                        "indexes": [
                            models.Index(
                                fields=["job_id", "-created_at", "-id", "job_state"],
                                name="qjs_job_id_desc_state_idx",
                            ),
                        ],
                    },
                ),
                migrations.CreateModel(
                    name="QueueJobLease",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                            ),
                        ),
                        ("lane", models.CharField(max_length=16)),
                        ("group_key", models.CharField(max_length=400)),
                        (
                            "owner_token",
                            models.CharField(
                                help_text="Per-pod identity (uuid4) of the current lease holder.",
                                max_length=64,
                            ),
                        ),
                        ("expires_at", models.DateTimeField()),
                        ("acquired_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "db_table": "queuejoblease",
                        "constraints": [
                            models.UniqueConstraint(fields=("lane", "group_key"), name="qjl_lane_group_uniq")
                        ],
                        "indexes": [
                            models.Index(fields=["expires_at"], name="qjl_expires_at_idx"),
                        ],
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(
            _create_generic_job_tables,
            _drop_generic_job_tables,
        ),
    ]
