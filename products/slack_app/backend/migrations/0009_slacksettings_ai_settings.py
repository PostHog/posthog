from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0008_slackthreadtaskmapping_last_forwarded_ts"),
    ]

    operations = [
        migrations.AddField(
            model_name="slacksettings",
            name="ai_preferences",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
