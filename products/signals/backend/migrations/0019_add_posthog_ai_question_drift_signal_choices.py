from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0018_alter_signalreportartefact_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signalsourceconfig",
            name="source_product",
            field=models.CharField(
                choices=[
                    ("session_replay", "Session replay"),
                    ("llm_analytics", "LLM analytics"),
                    ("github", "GitHub"),
                    ("linear", "Linear"),
                    ("zendesk", "Zendesk"),
                    ("conversations", "Conversations"),
                    ("error_tracking", "Error tracking"),
                    ("posthog_ai", "PostHog AI"),
                ],
                max_length=100,
            ),
        ),
        migrations.AlterField(
            model_name="signalsourceconfig",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("session_analysis_cluster", "Session analysis cluster"),
                    ("evaluation", "Evaluation"),
                    ("issue", "Issue"),
                    ("ticket", "Ticket"),
                    ("issue_created", "Issue created"),
                    ("issue_reopened", "Issue reopened"),
                    ("issue_spiking", "Issue spiking"),
                    ("question_drift", "Question drift"),
                ],
                max_length=100,
            ),
        ),
    ]
