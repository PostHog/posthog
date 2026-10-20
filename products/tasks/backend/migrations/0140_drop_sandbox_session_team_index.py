from django.db import migrations

from posthog.migration_helpers import DropFieldIndexesConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0139_remove_loop_models"),
    ]

    operations = [
        DropFieldIndexesConcurrently(model_name="sandboxsession", name="team"),
    ]
