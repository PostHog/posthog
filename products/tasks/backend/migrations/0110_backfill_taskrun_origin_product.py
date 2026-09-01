from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently

BATCH_SIZE = 2000


def backfill_origin_product(apps, schema_editor):
    # Copy each run's parent task origin_product onto the run. Keyset-paginate over the
    # run id so the backfill runs in bounded batches and every row is visited once.
    TaskRun = apps.get_model("tasks", "TaskRun")
    last_id = None
    with schema_editor.connection.cursor() as cursor:
        while True:
            qs = TaskRun.objects.order_by("id")
            if last_id is not None:
                qs = qs.filter(id__gt=last_id)
            ids = list(qs.values_list("id", flat=True)[:BATCH_SIZE])
            if not ids:
                break
            last_id = ids[-1]
            cursor.execute(
                """
                UPDATE posthog_task_run tr
                SET origin_product = t.origin_product
                FROM posthog_task t
                WHERE tr.task_id = t.id AND tr.id = ANY(%s)
                """,
                [ids],
            )


class Migration(migrations.Migration):
    # Non-atomic: the backfill runs in bounded batches without one long transaction, and
    # the concurrent index build cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("tasks", "0109_taskrun_origin_product"),
    ]

    operations = [
        migrations.RunPython(backfill_origin_product, migrations.RunPython.noop),
        SafeAddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                fields=["status", "environment", "origin_product"],
                name="task_run_status_env_origin_idx",
            ),
        ),
    ]
