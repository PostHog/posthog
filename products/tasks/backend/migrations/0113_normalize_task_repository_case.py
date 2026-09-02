from django.db import migrations

BATCH_SIZE = 2000


def normalize_repository_case(apps, schema_editor):
    # Task.save lowercases repository, but rows written before it did can still hold mixed
    # case. The GitHub webhook lookup now compares exactly, so normalize them once. Keyset
    # pagination over the task id keeps the write in bounded batches.
    Task = apps.get_model("tasks", "Task")
    last_id = None
    with schema_editor.connection.cursor() as cursor:
        while True:
            qs = Task.objects.order_by("id")
            if last_id is not None:
                qs = qs.filter(id__gt=last_id)
            ids = list(qs.values_list("id", flat=True)[:BATCH_SIZE])
            if not ids:
                break
            last_id = ids[-1]
            cursor.execute(
                """
                UPDATE posthog_task
                SET repository = lower(repository)
                WHERE id = ANY(%s) AND repository <> lower(repository)
                """,
                [ids],
            )


class Migration(migrations.Migration):
    # Non-atomic so the backfill runs in bounded batches without one long transaction.
    atomic = False

    dependencies = [
        ("tasks", "0112_taskrun_terminal_updated_idx"),
    ]

    operations = [
        migrations.RunPython(normalize_repository_case, migrations.RunPython.noop),
    ]
