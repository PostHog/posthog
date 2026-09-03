from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def clear_disconnected_channel_repositories(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Channel = apps.get_model("tasks", "Channel")
    Channel.objects.filter(github_integration__isnull=True).exclude(repositories=[]).update(repositories=[])


class Migration(migrations.Migration):
    dependencies = [("tasks", "0085_sandboxsession_cpu_attribution_usage")]

    operations = [
        migrations.RunPython(clear_disconnected_channel_repositories, migrations.RunPython.noop),
    ]
