from django.db import migrations

BATCH_SIZE = 1000


def remove_deleted_experiment_file_system_entries(apps, schema_editor):
    # Soft-deleted experiments kept their FileSystem row, so they stayed in Recents, the project
    # tree, the home dashboard, and search and opened an "Experiment not found" page. The model now
    # deletes the row on soft delete, but rows already orphaned do not re-save on their own — remove
    # them here. Mirrors delete_file: drop the FileSystem entry and any FileSystemShortcut to it.
    Experiment = apps.get_model("experiments", "Experiment")
    FileSystem = apps.get_model("posthog", "FileSystem")
    FileSystemShortcut = apps.get_model("posthog", "FileSystemShortcut")

    deleted_ids = list(Experiment.objects.filter(deleted=True).values_list("id", flat=True).order_by("id"))

    for start in range(0, len(deleted_ids), BATCH_SIZE):
        refs = [str(experiment_id) for experiment_id in deleted_ids[start : start + BATCH_SIZE]]
        FileSystem.objects.filter(type="experiment", ref__in=refs).delete()
        FileSystemShortcut.objects.filter(type="experiment", ref__in=refs).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0032_teamexperimentsconfig_flag_cleanup_repository"),
        ("posthog", "0733_file_system_shortcut"),
    ]

    operations = [
        migrations.RunPython(remove_deleted_experiment_file_system_entries, migrations.RunPython.noop),
    ]
