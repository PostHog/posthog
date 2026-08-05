from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0007_slackuserprofilecache_is_bot"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackthreadtaskmapping",
            name="last_forwarded_ts",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
