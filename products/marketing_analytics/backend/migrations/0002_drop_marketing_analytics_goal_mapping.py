# Generated manually for revert
# Phase 1: Remove model from Django state only (table remains for rollback safety)
# Phase 2: Drop the actual table in a future migration after this is deployed

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("marketing_analytics", "0001_add_marketing_analytics_goal_mapping"),
    ]

    operations = [
        # Remove MarketingAnalyticsGoalMapping from Django state only
        # The table will remain in the database for rollback safety
        # A future migration can drop the table after this is fully deployed
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="MarketingAnalyticsGoalMapping",
                ),
            ],
            database_operations=[],
        ),
    ]
