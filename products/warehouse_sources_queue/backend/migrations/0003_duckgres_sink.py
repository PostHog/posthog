import django.db.models.manager
import django.db.models.deletion
from django.db import migrations, models

from posthog.models.utils import uuid7

PARTITIONS_AHEAD = 7


def _create_duckgres_tables(apps, schema_editor):
    schema_editor.execute("""
        CREATE TABLE sourcebatchduckgresstatus (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);

        CREATE INDEX sbdgs_batch_desc_state_idx
            ON sourcebatchduckgresstatus (batch_id, created_at DESC, id DESC, job_state);

        CREATE TABLE sourcebatchduckgresstatus_default PARTITION OF sourcebatchduckgresstatus DEFAULT;
    """)

    schema_editor.execute("""
        CREATE TABLE sourcebatchduckgresapply (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            run_uuid VARCHAR(200) NOT NULL,
            batch_index INT NOT NULL,
            batch_id UUID NOT NULL,
            row_count INT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sbdga_unique_batch_apply UNIQUE (team_id, schema_id, run_uuid, batch_index)
        );

        CREATE INDEX sbdga_run_idx
            ON sourcebatchduckgresapply (team_id, schema_id, run_uuid);

        CREATE INDEX sbdga_team_id_idx
            ON sourcebatchduckgresapply (team_id);
    """)

    schema_editor.execute(f"""
        DO $$
        DECLARE
            d DATE;
        BEGIN
            FOR d IN SELECT generate_series(
                CURRENT_DATE,
                CURRENT_DATE + {PARTITIONS_AHEAD},
                '1 day'::interval
            )::date
            LOOP
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS sourcebatchduckgresstatus_%%s '
                    'PARTITION OF sourcebatchduckgresstatus '
                    'FOR VALUES FROM (%%L) TO (%%L)',
                    to_char(d, 'YYYYMMDD'), d, d + 1
                );
            END LOOP;
        END $$;
    """)


def _create_latest_duckgres_status_view(apps, schema_editor):
    schema_editor.execute("""
        CREATE VIEW v_latest_source_batch_duckgres_status AS
        SELECT DISTINCT ON (batch_id) *
        FROM sourcebatchduckgresstatus
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)


def _drop_duckgres_tables(apps, schema_editor):
    schema_editor.execute("DROP VIEW IF EXISTS v_latest_source_batch_duckgres_status")
    schema_editor.execute("DROP TABLE IF EXISTS sourcebatchduckgresapply CASCADE")
    schema_editor.execute("DROP TABLE IF EXISTS sourcebatchduckgresstatus CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0002_sourcebatch_run_uuid_batch_index_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="SourceBatchDuckgresStatus",
                    fields=[
                        (
                            "id",
                            models.UUIDField(default=uuid7, editable=False, primary_key=True, serialize=False),
                        ),
                        (
                            "job_state",
                            models.CharField(
                                choices=[
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
                        (
                            "batch",
                            models.ForeignKey(
                                db_constraint=False,
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                related_name="duckgres_statuses",
                                to="warehouse_sources_queue.sourcebatch",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "sourcebatchduckgresstatus",
                        "indexes": [
                            models.Index(
                                fields=["batch_id", "-created_at", "-id", "job_state"],
                                name="sbdgs_batch_desc_state_idx",
                            )
                        ],
                    },
                ),
                migrations.CreateModel(
                    name="SourceBatchDuckgresApply",
                    fields=[
                        (
                            "id",
                            models.UUIDField(default=uuid7, editable=False, primary_key=True, serialize=False),
                        ),
                        ("team_id", models.BigIntegerField(db_index=True)),
                        ("schema_id", models.CharField(max_length=200)),
                        ("run_uuid", models.CharField(max_length=200)),
                        ("batch_index", models.IntegerField()),
                        ("row_count", models.IntegerField()),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "batch",
                            models.ForeignKey(
                                db_constraint=False,
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                related_name="duckgres_applies",
                                to="warehouse_sources_queue.sourcebatch",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "sourcebatchduckgresapply",
                        "indexes": [models.Index(fields=["team_id", "schema_id", "run_uuid"], name="sbdga_run_idx")],
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("team_id", "schema_id", "run_uuid", "batch_index"),
                                name="sbdga_unique_batch_apply",
                            )
                        ],
                    },
                    managers=[
                        ("all_teams", django.db.models.manager.Manager()),
                    ],
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(_create_duckgres_tables, _drop_duckgres_tables),
        migrations.RunPython(
            _create_latest_duckgres_status_view,
            lambda apps, schema_editor: schema_editor.execute(
                "DROP VIEW IF EXISTS v_latest_source_batch_duckgres_status"
            ),
        ),
    ]
