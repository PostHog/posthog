from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0018_alter_signalreportartefact_type")]

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
                    ("pganalyze", "pganalyze"),
                ],
                max_length=100,
            ),
        ),
    ]
