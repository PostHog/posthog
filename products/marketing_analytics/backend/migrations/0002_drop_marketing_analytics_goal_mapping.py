# Generated manually for revert

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("marketing_analytics", "0001_add_marketing_analytics_goal_mapping"),
    ]

    operations = [
        migrations.DeleteModel(
            name="MarketingAnalyticsGoalMapping",
        ),
    ]
