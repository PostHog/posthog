from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("endpoints", "0014_endpoint_soft_delete"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="endpoint",
                    constraint=models.UniqueConstraint(
                        condition=Q(deleted=False) | Q(deleted__isnull=True),
                        fields=["team", "name"],
                        name="unique_team_endpoint_name_active",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "unique_team_endpoint_name_active" ON "endpoints_endpoint" ("team_id", "name") WHERE (NOT "deleted" OR "deleted" IS NULL)',
                    reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "unique_team_endpoint_name_active"',
                ),
                migrations.RunSQL(
                    sql='ALTER TABLE "endpoints_endpoint" ADD CONSTRAINT "unique_team_endpoint_name_active" UNIQUE USING INDEX "unique_team_endpoint_name_active"',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
