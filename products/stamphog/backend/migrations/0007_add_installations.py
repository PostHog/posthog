import django.db.models.manager
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    """Add the team-to-installation link that holds the repositories a team can add."""

    dependencies = [
        ("stamphog", "0006_change_summaries_hold_a_clause_per_team"),
    ]

    operations = [
        migrations.CreateModel(
            name="StamphogInstallation",
            fields=[
                ("team_id", models.BigIntegerField(db_index=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("provider", models.CharField(default="github", max_length=32)),
                ("installation_id", models.CharField(max_length=64)),
                ("repositories", models.JSONField(default=list)),
                ("connected_by_user_id", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "abstract": False,
                "default_manager_name": "all_teams",
                "indexes": [
                    models.Index(
                        fields=["provider", "installation_id"],
                        name="stamphog_installation_lookup",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team_id", "provider", "installation_id"),
                        name="unique_stamphog_installation_per_team",
                    )
                ],
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
    ]
