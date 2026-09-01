from django.db import migrations, models

from posthog.migration_helpers.concurrent_index import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("managed_migrations", "0002_alter_batchimport_secrets_nullable"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="batchimport",
            index=models.Index(
                fields=["created_at"],
                name="batchimport_running_claim_idx",
                condition=models.Q(status="running"),
            ),
        ),
    ]
