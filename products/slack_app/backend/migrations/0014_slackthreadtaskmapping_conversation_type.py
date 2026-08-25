from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0013_slacksettings_untagged_followup_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackthreadtaskmapping",
            name="conversation_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("im", "Direct message"),
                    ("mpim", "Group direct message"),
                    ("public_channel", "Public channel"),
                    ("private_channel", "Private channel"),
                    ("unknown", "Unknown"),
                ],
                max_length=16,
                null=True,
            ),
        ),
    ]
