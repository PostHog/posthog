import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("product_analytics", "0008_repair_insightviewed_null_unique_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="InsightDataModelDependency",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("saved_query_id", models.UUIDField()),
                ("query_fingerprint", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "insight",
                    models.ForeignKey(
                        db_constraint=False,
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="product_analytics.insight",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_insightdatamodeldependency",
                "indexes": [
                    models.Index(
                        fields=["team", "saved_query_id", "insight"],
                        name="insight_dmdep_team_sq_ins_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team", "insight", "saved_query_id"),
                        name="insight_dmdep_team_ins_sq_uniq",
                    )
                ],
            },
        ),
    ]
