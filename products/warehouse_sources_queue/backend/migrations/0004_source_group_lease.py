from django.db import migrations, models


def _create_group_lease_table(apps, schema_editor):
    schema_editor.execute("""
        CREATE TABLE sourcegrouplease (
            id BIGSERIAL PRIMARY KEY,
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            owner_token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sgl_team_schema_uniq UNIQUE (team_id, schema_id)
        )
    """)
    schema_editor.execute("""
        CREATE INDEX sgl_expires_at_idx ON sourcegrouplease (expires_at)
    """)


def _drop_group_lease_table(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS sourcegrouplease CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources_queue", "0003_duckgres_sink"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="SourceGroupLease",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                            ),
                        ),
                        ("team_id", models.BigIntegerField()),
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
                        "db_table": "sourcegrouplease",
                        "constraints": [
                            models.UniqueConstraint(fields=("team_id", "schema_id"), name="sgl_team_schema_uniq")
                        ],
                        "indexes": [models.Index(fields=["expires_at"], name="sgl_expires_at_idx")],
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(_create_group_lease_table, _drop_group_lease_table),
    ]
