from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestra", "0002_add_team_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="Deployment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("code_version", models.CharField(max_length=64)),
                ("image_name", models.CharField(max_length=512)),
                ("container_id", models.CharField(blank=True, default="", max_length=128)),
                ("task_queue", models.CharField(max_length=255)),
                ("status", models.CharField(default="active", max_length=32)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.JSONField(blank=True, null=True)),
            ],
            options={
                "default_manager_name": "all_teams",
                "indexes": [
                    models.Index(fields=["team_id", "status"], name="orch_dep_team_status_idx"),
                    models.Index(fields=["team_id", "-started_at"], name="orch_dep_team_started_idx"),
                ],
            },
        ),
    ]
