import django.db.models.manager
from django.db import migrations, models


def _create_duckgres_group_lease_table(apps, schema_editor):
    schema_editor.execute("""
        CREATE TABLE sourceduckgresgrouplease (
            id BIGSERIAL PRIMARY KEY,
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            owner_token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sdgl_team_schema_uniq UNIQUE (team_id, schema_id)
        )
    """)
    schema_editor.execute("""
        CREATE INDEX sdgl_expires_at_idx ON sourceduckgresgrouplease (expires_at)
    """)
    schema_editor.execute("""
        CREATE INDEX sdgl_team_id_idx ON sourceduckgresgrouplease (team_id)
    """)


def _drop_duckgres_group_lease_table(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS sourceduckgresgrouplease CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0004_source_group_lease"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="SourceDuckgresGroupLease",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                            ),
                        ),
                        ("team_id", models.BigIntegerField(db_index=True)),
                        ("schema_id", models.CharField(max_length=200)),
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
                        "db_table": "sourceduckgresgrouplease",
                        "indexes": [models.Index(fields=["expires_at"], name="sdgl_expires_at_idx")],
                        "constraints": [
                            models.UniqueConstraint(fields=("team_id", "schema_id"), name="sdgl_team_schema_uniq")
                        ],
                    },
                    managers=[
                        ("all_teams", django.db.models.manager.Manager()),
                    ],
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(_create_duckgres_group_lease_table, _drop_duckgres_group_lease_table),
    ]
