from django.db import migrations


def backfill_task_repositories(apps, schema_editor):
    while True:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE posthog_task
                SET repositories = ARRAY[LOWER(repository)]
                WHERE id IN (
                    SELECT id
                    FROM posthog_task
                    WHERE repositories = '{}' AND repository IS NOT NULL AND repository <> ''
                    LIMIT 10000
                )
                """
            )
            if cursor.rowcount == 0:
                return


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("tasks", "0078_task_repositories")]

    operations = [migrations.RunPython(backfill_task_repositories, migrations.RunPython.noop)]
