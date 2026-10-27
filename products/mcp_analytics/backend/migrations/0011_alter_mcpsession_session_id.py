from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_analytics", "0010_alter_mcpanalyticssubmission_team_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mcpsession",
            name="session_id",
            field=models.CharField(max_length=128),
        ),
    ]
