from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only AlterField — `choices` is enforced at the application layer, no DB-level change."""

    dependencies = [("tasks", "0037_codeworkflowconfig_codeprsnapshot_codeworkstream")]

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
                    ("signals_scout", "Signals Scout"),
                    ("support_reply", "Support Reply"),
                ],
                max_length=20,
            ),
        ),
    ]
