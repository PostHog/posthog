from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0054_alter_signalsourceconfig_source_type"),
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
                    ("jira", "Jira"),
                    ("zendesk", "Zendesk"),
                    ("conversations", "Conversations"),
                    ("error_tracking", "Error tracking"),
                    ("pganalyze", "pganalyze"),
                    ("signals_scout", "Signals scout"),
                    ("logs", "Logs"),
                    ("health_checks", "Health checks"),
                    ("endpoints", "Endpoints"),
                    ("replay_vision", "Replay Vision"),
                ],
                max_length=100,
            ),
        ),
    ]
