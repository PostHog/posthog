from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("growth", "0010_icp_scoring_rules"),
    ]

    operations = [
        migrations.CreateModel(
            name="SdkVersionsDaily",
            fields=[
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "team_id",
                        "day",
                        "lib",
                        "lib_version",
                        blank=True,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField()),
                ("day", models.DateField()),
                ("lib", models.CharField(max_length=64)),
                ("lib_version", models.CharField(max_length=64)),
                ("event_count", models.BigIntegerField()),
                ("max_timestamp", models.DateTimeField()),
            ],
            options={
                "db_table": "growth_sdk_versions_daily",
                "indexes": [models.Index(fields=["day"], name="growth_sdk_ver_daily_day_idx")],
            },
        ),
    ]
