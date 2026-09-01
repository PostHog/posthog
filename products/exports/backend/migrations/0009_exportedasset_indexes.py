from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("exports", "0008_exportedasset_source_authentication"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="exportedasset",
            index=models.Index(fields=["team", "-created_at"], name="expasset_team_created"),
        ),
        SafeAddIndexConcurrently(
            model_name="exportedasset",
            index=models.Index(
                fields=["team", "insight", "dashboard", "export_format"],
                name="expasset_team_ins_dash_fmt",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="exportedasset",
            index=models.Index(fields=["expires_after"], name="expasset_expires_after"),
        ),
    ]
