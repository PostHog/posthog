from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("web_analytics", "0017_webanalyticsachievementprogress_retry_backoff"),
    ]

    operations = [
        migrations.CreateModel(
            name="EventsHealthDaily",
            fields=[
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "team_id",
                        "day",
                        "event",
                        "has_custom_api_host",
                        "has_scroll_depth",
                        "session_id_state",
                        blank=True,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField()),
                ("day", models.DateField()),
                ("event", models.CharField(max_length=32)),
                ("has_custom_api_host", models.BooleanField()),
                ("has_scroll_depth", models.BooleanField()),
                (
                    "session_id_state",
                    models.SmallIntegerField(
                        choices=[
                            (0, "Not applicable"),
                            (1, "Valid"),
                            (2, "Not UUIDv7"),
                            (3, "Absent or not a UUID"),
                        ]
                    ),
                ),
                ("event_count", models.BigIntegerField()),
            ],
            options={
                "db_table": "web_analytics_events_health_daily",
                "indexes": [models.Index(fields=["day"], name="wa_events_health_daily_day_idx")],
            },
        ),
        migrations.CreateModel(
            name="HostProxyDaily",
            fields=[
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "team_id",
                        "day",
                        "host",
                        "has_custom_api_host",
                        blank=True,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField()),
                ("day", models.DateField()),
                ("host", models.CharField(max_length=253)),
                ("has_custom_api_host", models.BooleanField()),
                ("event_count", models.BigIntegerField()),
            ],
            options={
                "db_table": "web_analytics_host_proxy_daily",
                "indexes": [models.Index(fields=["day"], name="wa_host_proxy_daily_day_idx")],
            },
        ),
    ]
