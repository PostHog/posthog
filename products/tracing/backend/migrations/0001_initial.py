import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.utils
import posthog.models.utils


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
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
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
    ]
