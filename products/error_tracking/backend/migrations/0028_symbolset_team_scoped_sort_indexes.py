from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("error_tracking", "0027_add_severity_rules"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="errortrackingsymbolset",
            index=models.Index(fields=["team", "last_used"], name="et_symset_team_used_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="errortrackingsymbolset",
            index=models.Index(fields=["team", "created_at"], name="et_symset_team_created_idx"),
        ),
    ]
