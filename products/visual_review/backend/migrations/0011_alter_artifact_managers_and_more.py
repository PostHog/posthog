# Generated for the `default_manager_name = "all_teams"` change on
# `ProductTeamModel.Meta`. State-only — no SQL emitted. Records the
# manager configuration in migration state so future migrations stay
# consistent with the model definitions.

from django.db import migrations, models

import posthog.models.scoping.manager


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0010_backfill_change_kind_and_ssim"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="artifact",
            options={"default_manager_name": "all_teams"},
        ),
        migrations.AlterModelOptions(
            name="quarantinedidentifier",
            options={"default_manager_name": "all_teams"},
        ),
        migrations.AlterModelOptions(
            name="repo",
            options={"default_manager_name": "all_teams"},
        ),
        migrations.AlterModelOptions(
            name="run",
            options={
                "default_manager_name": "all_teams",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AlterModelOptions(
            name="runsnapshot",
            options={"default_manager_name": "all_teams"},
        ),
        migrations.AlterModelOptions(
            name="toleratedhash",
            options={"default_manager_name": "all_teams"},
        ),
        migrations.AlterModelManagers(
            name="artifact",
            managers=[
                ("objects", posthog.models.scoping.manager.TeamScopedManager()),
                ("all_teams", models.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="quarantinedidentifier",
            managers=[
                ("objects", posthog.models.scoping.manager.TeamScopedManager()),
                ("all_teams", models.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="repo",
            managers=[
                ("objects", posthog.models.scoping.manager.TeamScopedManager()),
                ("all_teams", models.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="run",
            managers=[
                ("objects", posthog.models.scoping.manager.TeamScopedManager()),
                ("all_teams", models.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="runsnapshot",
            managers=[
                ("objects", posthog.models.scoping.manager.TeamScopedManager()),
                ("all_teams", models.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="toleratedhash",
            managers=[
                ("objects", posthog.models.scoping.manager.TeamScopedManager()),
                ("all_teams", models.Manager()),
            ],
        ),
    ]
