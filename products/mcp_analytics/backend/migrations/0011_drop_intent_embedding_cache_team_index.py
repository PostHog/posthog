from django.db import migrations

from posthog.migration_helpers import DropFieldIndexesConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("mcp_analytics", "0010_alter_mcpanalyticssubmission_team_and_more"),
    ]

    operations = [
        DropFieldIndexesConcurrently(model_name="mcpintentembeddingcache", name="team"),
    ]
