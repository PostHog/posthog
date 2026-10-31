from django.db import migrations

SCALE_FACTOR = 0.02
TABLES = ("web_analytics_events_health_daily", "web_analytics_host_proxy_daily")


class Migration(migrations.Migration):
    dependencies = [
        ("web_analytics", "0018_daily_health_rollups"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "SET LOCAL lock_timeout = '5s'",
                *(
                    f"ALTER TABLE {table} SET (autovacuum_vacuum_scale_factor = {SCALE_FACTOR}, "
                    f"autovacuum_analyze_scale_factor = {SCALE_FACTOR})"
                    for table in TABLES
                ),
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                *(
                    f"ALTER TABLE {table} RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)"
                    for table in TABLES
                ),
            ],
        ),
    ]
