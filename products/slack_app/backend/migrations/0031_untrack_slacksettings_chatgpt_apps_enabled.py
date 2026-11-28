from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0030_chatgpt_apps_mode_and_thread_joins"),
    ]

    operations = [
        untrack_field("slacksettings", "chatgpt_apps_enabled"),
    ]
