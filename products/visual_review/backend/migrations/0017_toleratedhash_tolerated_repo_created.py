from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("visual_review", "0016_quarantinedidentifier_lifted_at_sha"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="toleratedhash",
            index=models.Index(fields=["repo", "created_at"], name="tolerated_repo_created"),
        ),
    ]
