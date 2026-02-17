from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("endpoints", "0014_endpoint_soft_delete"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql='CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "team_id_endpoint_name_active" ON "endpoints_endpoint" ("team_id", "name") WHERE (NOT "deleted" OR "deleted" IS NULL)',
                    reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "team_id_endpoint_name_active"',
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="endpoint",
                    index=models.Index(
                        condition=models.Q(("deleted", False), ("deleted__isnull", True), _connector="OR"),
                        fields=["team", "name"],
                        name="team_id_endpoint_name_active",
                    ),
                ),
            ],
        )
    ]
