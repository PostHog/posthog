import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.db import migrations

from posthog.migration_helpers.concurrent_index import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("mcp_registry", "0003_standalone_row_owner"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="mcpregistrytool",
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Upper("name"), name="gin_trgm_ops"
                ),
                name="mcp_registry_tool_name_trgm",
            ),
        ),
    ]
