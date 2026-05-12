# State-only — records the new `all_teams` manager on each
# `ProductTeamModel`-backed model. No SQL emitted; just keeps Django's
# migration state in sync with the model definitions after
# `posthog/models/scoping/product_mixin.py` started exposing a sibling
# unscoped manager alongside `objects`.

import django.db.models.manager
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0010_backfill_change_kind_and_ssim"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="artifact",
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="quarantinedidentifier",
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="repo",
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="run",
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="runsnapshot",
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="toleratedhash",
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
    ]
