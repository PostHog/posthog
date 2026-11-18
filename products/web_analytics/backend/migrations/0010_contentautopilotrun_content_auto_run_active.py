from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("web_analytics", "0009_content_autopilot"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="contentautopilotrun",
            index=models.Index(
                condition=models.Q(("run_status__in", ["pending", "generating"])),
                fields=["profile"],
                name="content_auto_run_active",
            ),
        ),
    ]
