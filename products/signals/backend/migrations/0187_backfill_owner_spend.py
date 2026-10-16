from django.db import migrations, transaction


def backfill_owner_spend(apps, schema_editor):
    Source = apps.get_model("signals", "LegacySignalSpend")
    Spend = apps.get_model("signals", "SignalSpend")
    TaskRun = apps.get_model("tasks", "TaskRun")
    alias = schema_editor.connection.alias
    last_id = None
    while True:
        sources = Source._base_manager.using(alias).order_by("id")
        if last_id is not None:
            sources = sources.filter(id__gt=last_id)
        batch = list(sources[:500])
        if not batch:
            return
        runs = {
            str(run["id"]): run
            for run in TaskRun._base_manager.using(alias)
            .filter(id__in=[source.source_id for source in batch if source.is_task])
            .values("id", "task__signal_report_id")
        }
        with transaction.atomic(using=alias):
            for source in batch:
                owner = {"signal_id": source.signal_id} if source.signal_id else {"scout_run_id": source.scout_run_id}
                spend, _ = Spend._base_manager.using(alias).get_or_create(
                    team_id=source.team_id,
                    **owner,
                    defaults={"pending_work": ["pipeline"] if source.signal_id else []},
                )
                spend = Spend._base_manager.using(alias).select_for_update().get(id=spend.id)
                key = f"task:{source.source_id}" if source.is_task else source.source_id
                previous = spend.sources.get(key)
                if previous and previous["updated_at"] >= source.updated_at.isoformat():
                    continue
                run = runs.get(source.source_id)
                spend.sources[key] = {
                    "cost_microusd": source.token_cost_microusd
                    if source.token_cost_microusd is not None
                    else (previous["cost_microusd"] if previous else None),
                    "stage": source.stage,
                    "is_task": source.is_task,
                    "task_id": str(source.task_id) if source.task_id else None,
                    "accounting_failed": source.accounting_failed,
                    # A terminal TaskRun status does not prove workflow teardown has finished.
                    "finished": previous["finished"] if previous else not source.is_task,
                    "updated_at": source.updated_at.isoformat(),
                }
                if source.task_id and source.task_id not in spend.task_ids:
                    spend.task_ids.append(source.task_id)
                if run and run["task__signal_report_id"]:
                    spend.report_id = run["task__signal_report_id"]
                spend.token_cost_microusd = sum(item["cost_microusd"] or 0 for item in spend.sources.values())
                spend.task_count = sum(item["is_task"] for item in spend.sources.values())
                spend.accounting_failed = any(item["accounting_failed"] for item in spend.sources.values())
                spend.finalized_at = None
                spend.save(using=alias)
        last_id = batch[-1].id


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("signals", "0186_owner_spend"), ("tasks", "0121_squash_2026_09_07_finalize_fks")]
    operations = [migrations.RunPython(backfill_owner_spend, reverse_code=migrations.RunPython.noop)]
