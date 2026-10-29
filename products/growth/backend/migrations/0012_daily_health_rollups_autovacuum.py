from django.db import migrations

SCALE_FACTOR = 0.02


class Migration(migrations.Migration):
    dependencies = [
        ("growth", "0011_daily_health_rollups"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE growth_sdk_versions_daily SET (autovacuum_vacuum_scale_factor = {SCALE_FACTOR}, autovacuum_analyze_scale_factor = {SCALE_FACTOR})",
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                "ALTER TABLE growth_sdk_versions_daily RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)",
            ],
        ),
    ]
