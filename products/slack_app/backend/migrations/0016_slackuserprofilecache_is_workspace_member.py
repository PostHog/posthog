from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0015_backfill_slack_thread_conversation_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackuserprofilecache",
            name="is_workspace_member",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
