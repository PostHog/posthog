from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("web_analytics", "0010_contentautopilotrun_content_auto_run_active"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="webanalyticsfilterpreset",
            name="wa_preset_del_mod_idx",
        ),
    ]
