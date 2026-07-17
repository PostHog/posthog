from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only AlterField — `choices` is enforced at the application layer, no DB-level change."""

    dependencies = [
        ("tasks", "0043_alter_task_origin_product"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="origin_product",
            field=models.CharField(
                choices=[
                    ("onboarding", "Onboarding"),
                    ("error_tracking", "Error Tracking"),
                    ("eval_clusters", "Eval Clusters"),
                    ("user_created", "User Created"),
                    ("automation", "Automation"),
                    ("slack", "Slack"),
                    ("support_queue", "Support Queue"),
                    ("session_summaries", "Session Summaries"),
                    ("posthog_ai", "PostHog AI"),
                    ("signal_report", "Signal Report"),
                    ("signals_scout", "Signals Scout"),
                    ("support_reply", "Support Reply"),
                    ("hogdesk", "HogDesk"),
                ],
                max_length=20,
            ),
        ),
    ]
