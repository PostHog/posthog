from django.db import migrations
from django.db.models import Count

# Kept small so each batch holds only short-lived locks and bounded memory.
GROUP_BATCH = 100
REF_BATCH = 500
DELETE_BATCH = 500


def dedupe_sandbox_environments(apps, schema_editor):
    """Collapse duplicate (team, name) sandbox environments to the most recent row.

    Required before the unique constraint can be added. Repoints TaskRun.state
    references off the surplus rows, then deletes them. Queries are batched so the
    whole table is never loaded into memory; idempotent.
    """
    SandboxEnvironment = apps.get_model("tasks", "SandboxEnvironment")
    TaskRun = apps.get_model("tasks", "TaskRun")

    while True:
        groups = list(
            SandboxEnvironment.objects.values("team_id", "name")
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .order_by()[:GROUP_BATCH]
        )
        if not groups:
            break

        for group in groups:
            row_ids = list(
                SandboxEnvironment.objects.filter(team_id=group["team_id"], name=group["name"])
                .order_by("-created_at", "-id")
                .values_list("id", flat=True)
            )
            keeper_id = str(row_ids[0])
            surplus_ids = row_ids[1:]
            surplus_str = [str(env_id) for env_id in surplus_ids]

            # TaskRun.state JSON holds the only references (no DB FK). Updated runs
            # stop matching the filter, so the loop drains them a batch at a time.
            while True:
                run_ids = list(
                    TaskRun.objects.filter(state__sandbox_environment_id__in=surplus_str).values_list("id", flat=True)[
                        :REF_BATCH
                    ]
                )
                if not run_ids:
                    break
                runs = list(TaskRun.objects.filter(id__in=run_ids))
                for run in runs:
                    run.state["sandbox_environment_id"] = keeper_id
                TaskRun.objects.bulk_update(runs, ["state"])

            for start in range(0, len(surplus_ids), DELETE_BATCH):
                SandboxEnvironment.objects.filter(id__in=surplus_ids[start : start + DELETE_BATCH]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0038_task_origin_product_conversations_support"),
    ]

    operations = [
        migrations.RunPython(
            dedupe_sandbox_environments,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
