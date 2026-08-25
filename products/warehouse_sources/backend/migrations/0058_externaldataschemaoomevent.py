import django.db.models.manager
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1247_oauthaccesstoken_token_idx"),
        ("warehouse_sources", "0057_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalDataSchemaOOMEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("run_id", models.CharField(blank=True, max_length=400, null=True)),
                ("host", models.CharField(blank=True, max_length=400, null=True)),
                ("gap_seconds", models.FloatField(blank=True, null=True)),
                (
                    "schema",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="oom_events",
                        to="warehouse_sources.externaldataschema",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False, on_delete=django.db.models.deletion.CASCADE, to="posthog.team"
                    ),
                ),
            ],
            options={
                "default_manager_name": "all_teams",
                "indexes": [
                    models.Index(fields=["schema", "created_at"], name="dwh_oom_schema_created_idx"),
                ],
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
    ]
