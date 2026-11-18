from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0115_teamtasksconfig_usertasksconfig"),
    ]

    operations = [
        # No SeparateDatabaseAndState wrapper: Django never recorded this
        # auto-generated `_like` companion in migration state.
        DropIndexConcurrently(
            index_name="posthog_task_session_object_storage_key_68a9145c_like",
            table_name="posthog_task_session",
            columns='("object_storage_key" varchar_pattern_ops)',
        ),
    ]
