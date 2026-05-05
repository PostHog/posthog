from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only AlterField — `choices` is enforced at the application layer, no DB-level change."""

    dependencies = [("tasks", "0031_task_github_user_integration")]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="origin_product",
            field=models.CharField(
                choices=[
                    ("error_tracking", "Error Tracking"),
                    ("eval_clusters", "Eval Clusters"),
                    ("user_created", "User Created"),
                    ("automation", "Automation"),
                    ("slack", "Slack"),
                    ("support_queue", "Support Queue"),
                    ("session_summaries", "Session Summaries"),
                    ("signal_report", "Signal Report"),
                    ("signals_agent", "Signals Agent"),
                ],
                max_length=20,
            ),
        ),
    ]
