from django.db import migrations

OLD_TITLE = "Imported chat"
NEW_TITLE = "(no title)"


def _retitle(apps, schema_editor, old: str, new: str) -> None:
    Task = apps.get_model("tasks", "Task")
    Task.objects.using(schema_editor.connection.alias).filter(
        origin_product="posthog_ai",
        title=old,
        # A title the person set on the task outranks the one the copy generated.
        title_manually_set=False,
    ).update(title=new)


def retitle_forwards(apps, schema_editor):
    _retitle(apps, schema_editor, OLD_TITLE, NEW_TITLE)


def retitle_backwards(apps, schema_editor):
    _retitle(apps, schema_editor, NEW_TITLE, OLD_TITLE)


class Migration(migrations.Migration):
    dependencies = [("tasks", "0131_taskrun_github_pr_run_idx")]

    operations = [migrations.RunPython(retitle_forwards, retitle_backwards)]
