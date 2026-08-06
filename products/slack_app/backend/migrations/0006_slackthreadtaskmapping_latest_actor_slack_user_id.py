from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0005_slackchannel"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackthreadtaskmapping",
            name="latest_actor_slack_user_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
