import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.utils
import posthog.models.utils
from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posthog", "1245_duckgres_sink_schema_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="TracingView",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "short_id",
                    models.CharField(
                        blank=True,
                        default=posthog.utils.generate_short_id,
                        max_length=12,
                    ),
                ),
                ("name", models.CharField(max_length=400)),
                ("filters", models.JSONField(default=dict)),
                ("pinned", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "tracing_tracingview",
                "indexes": [
                    models.Index(
                        fields=["team_id", "-created_at"],
                        name="tracing_view_team_created_idx",
                    )
                ],
                "unique_together": {("team", "short_id")},
            },
        ),
        AddForeignKeyNotValid(
            model_name="tracingview",
            name="tracingview_team_id_fk",
            column="team_id",
            to_table="posthog_team",
            to_column="id",
        ),
        AddForeignKeyNotValid(
            model_name="tracingview",
            name="tracingview_created_by_id_fk",
            column="created_by_id",
            to_table="posthog_user",
            to_column="id",
        ),
    ]
