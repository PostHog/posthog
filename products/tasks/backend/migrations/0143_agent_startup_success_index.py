import django.db.models.fields.json
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1414_remove_filesystem_rows_for_deleted_insights"),
        ("tasks", "0142_task_profile_and_source"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                models.F("team"),
                django.db.models.fields.json.KeyTransform(
                    "repository",
                    django.db.models.fields.json.KeyTransform("agent_startup_success", "state"),
                ),
                django.db.models.fields.json.KeyTransform(
                    "provider",
                    django.db.models.fields.json.KeyTransform("agent_startup_success", "state"),
                ),
                django.db.models.fields.json.KeyTransform(
                    "runtime",
                    django.db.models.fields.json.KeyTransform("agent_startup_success", "state"),
                ),
                models.OrderBy(
                    django.db.models.fields.json.KeyTransform(
                        "started_at",
                        django.db.models.fields.json.KeyTransform("agent_startup_success", "state"),
                    ),
                    descending=True,
                ),
                condition=models.Q(("state__has_key", "agent_startup_success")),
                name="task_run_startup_success_idx",
            ),
        ),
    ]
