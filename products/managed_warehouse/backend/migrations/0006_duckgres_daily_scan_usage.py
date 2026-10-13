from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("managed_warehouse", "0005_duckgres_cursor_applied_watermark"),
    ]

    operations = [
        migrations.CreateModel(
            name="DuckgresDailyScanUsage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("date", models.DateField()),
                ("organization_id", models.UUIDField()),
                ("team_id", models.BigIntegerField()),
                ("query_source", models.CharField(max_length=32)),
                ("logical_bytes_scanned", models.DecimalField(max_digits=38, decimal_places=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            managers=[("all_teams", models.Manager())],
            options={
                "db_table": "posthog_duckgresdailyscanusage",
                "default_manager_name": "all_teams",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("date", "organization_id", "team_id", "query_source"),
                        name="duckgres_daily_scan_key",
                    )
                ],
            },
        ),
    ]
