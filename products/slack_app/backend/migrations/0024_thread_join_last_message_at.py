from django.db import migrations, models

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0023_slacksettings_feature_tips"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackthreadjoin",
            name="last_message_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # The column stays until a later drop, so pods on the old release keep working.
        untrack_field("slackthreadtaskmapping", "latest_actor_slack_user_id"),
    ]
