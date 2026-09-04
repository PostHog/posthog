from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0115_signalreportartefact_actor_agent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
