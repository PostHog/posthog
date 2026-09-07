from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the build takes no ACCESS EXCLUSIVE lock on mcp_registry_server.
    # Concurrent builds can't run in a transaction, so this migration is non-atomic.
    atomic = False

    dependencies = [
        ("mcp_registry", "0002_alter_mcpmeasuredstats_options_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="mcpregistryserver",
            index=models.Index(fields=["registry_name"], name="mcp_registry_name_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="mcpregistryserver",
            index=models.Index(
                fields=["display_name", "listed_in_registry", "is_measured"],
                name="mcp_registry_srv_name_idx",
            ),
        ),
    ]
