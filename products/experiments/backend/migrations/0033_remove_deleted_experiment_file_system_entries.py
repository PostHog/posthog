from collections import defaultdict

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

    # Every index on both tables leads with team_id, so a filter of only (type, ref) scans the whole
    # table. Bucket refs by team up front and include team_id in each delete so it becomes an index
    # range read instead.
    refs_by_team: dict[int, list[str]] = defaultdict(list)
    for team_id, experiment_id in (
        Experiment.objects.filter(deleted=True).values_list("team_id", "id").order_by("team_id", "id").iterator()
    ):
        refs_by_team[team_id].append(str(experiment_id))

    for team_id, refs in refs_by_team.items():
        for start in range(0, len(refs), BATCH_SIZE):
            batch = refs[start : start + BATCH_SIZE]
            FileSystem.objects.filter(team_id=team_id, type="experiment", ref__in=batch).delete()
            FileSystemShortcut.objects.filter(team_id=team_id, type="experiment", ref__in=batch).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0032_teamexperimentsconfig_flag_cleanup_repository"),
        ("posthog", "0733_file_system_shortcut"),
    ]

    operations = [
        migrations.RunPython(remove_deleted_experiment_file_system_entries, migrations.RunPython.noop),
    ]
