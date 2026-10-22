from uuid import UUID

from django.db import migrations, transaction


def backfill_owner_spend(apps, schema_editor):
    Source = apps.get_model("signals", "LegacySignalSpend")
    Spend = apps.get_model("signals", "SignalSpend")
    Scout = apps.get_model("signals", "SignalScoutRun")
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
                )
                spend = Spend._base_manager.using(alias).select_for_update().get(id=spend.id)
                if spend.finalized_at is not None:
                    continue
                run = runs.get(source.source_id)
                if source.is_task and UUID(source.source_id) not in spend.task_run_ids:
                    spend.task_run_ids.append(UUID(source.source_id))
                if run and run["task__signal_report_id"]:
                    spend.report_id = run["task__signal_report_id"]
                receipts = list(Source._base_manager.using(alias).filter(team_id=source.team_id, **owner))
                spend.created_at = min(spend.created_at, *(receipt.created_at for receipt in receipts))
                if source.scout_run_id:
                    scout_started = (
                        Scout._base_manager.using(alias)
                        .filter(id=source.scout_run_id, team_id=source.team_id)
                        .values_list("created_at", flat=True)
                        .first()
                    )
                    if scout_started is not None:
                        spend.created_at = min(spend.created_at, scout_started)
                spend.token_cost_microusd = spend.llm_cost_microusd + sum(
                    receipt.token_cost_microusd or 0 for receipt in receipts
                )
                spend.task_count = sum(receipt.is_task for receipt in receipts)
                spend.accounting_failed = bool(spend.llm_failed_stages) or any(
                    receipt.accounting_failed for receipt in receipts
                )
                spend.finalized_at = None
                spend.save(using=alias)
        last_id = batch[-1].id


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("signals", "0192_owner_spend"), ("tasks", "0121_squash_2026_09_07_finalize_fks")]
    operations = [migrations.RunPython(backfill_owner_spend, reverse_code=migrations.RunPython.noop)]
