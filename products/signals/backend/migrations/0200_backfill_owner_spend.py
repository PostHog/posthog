from decimal import Decimal
from uuid import UUID

from django.db import migrations, transaction


def backfill_owner_spend(apps, schema_editor):
    Source = apps.get_model("signals", "LegacySignalSpend")
    Spend = apps.get_model("signals", "SignalSpend")
    Scout = apps.get_model("signals", "SignalScoutRun")
    Run = apps.get_model("tasks", "TaskRun")
    alias = schema_editor.connection.alias
    last_id = None
    while True:
        sources = Source._base_manager.using(alias).order_by("id")
        if last_id is not None:
            sources = sources.filter(id__gt=last_id)
        batch = list(sources[:500])
        if not batch:
            return
        with transaction.atomic(using=alias):
            for source in batch:
                defaults = {"signal_id": source.signal_id, "scout_run_id": source.scout_run_id}
                if source.is_task:
                    run = (
                        Run._base_manager.using(alias)
                        .select_related("task__signal_report")
                        .only(
                            "id",
                            "created_at",
                            "task_id",
                            "task__id",
                            "task__signal_report_id",
                            "task__signal_report__billing_exempt_reason",
                        )
                        .filter(id=source.source_id, team_id=source.team_id)
                        .first()
                    )
                    if run is None:
                        continue
                    if source.scout_run_id:
                        defaults["kind"] = "scout_run"
                        scout = (
                            Scout._base_manager.using(alias)
                            .only("created_at", "trial_state")
                            .get(id=source.scout_run_id, team_id=source.team_id)
                        )
                        defaults["billing_exempt"] = scout.trial_state is not None
                    elif source.stage == "implementation" and run.task.signal_report_id:
                        # Legacy receipts did not distinguish implementation triggers; keep the default implementation kind.
                        defaults.update(
                            kind="reviewer_triggered_implementation",
                            signal_id=None,
                            report_id=run.task.signal_report_id,
                        )
                    elif source.stage in {"research", "repo_selection"}:
                        defaults["kind"] = source.stage
                    else:
                        continue
                    lookup: dict[str, object] = {"task_run_id": UUID(source.source_id)}
                    receipts = [source]
                    first_cost_at = (
                        min(source.created_at, run.created_at, scout.created_at)
                        if source.scout_run_id
                        else min(source.created_at, run.created_at)
                    )
                    if run.task.signal_report_id and run.task.signal_report.billing_exempt_reason:
                        defaults["billing_exempt"] = True
                else:
                    lookup = {"signal_id": source.signal_id, "kind": "ad-hoc"}
                    defaults = {}
                    receipts = list(
                        Source._base_manager.using(alias).filter(
                            team_id=source.team_id, signal_id=source.signal_id, is_task=False
                        )
                    )
                    first_cost_at = min(receipt.created_at for receipt in receipts)
                spend, created = Spend._base_manager.using(alias).get_or_create(
                    team_id=source.team_id,
                    **lookup,
                    defaults=defaults,
                )
                spend = Spend._base_manager.using(alias).select_for_update().get(id=spend.id)
                if spend.finalized_at is not None:
                    continue
                if not created and spend.kind == "ad-hoc" and spend.created_at < first_cost_at:
                    spend.accounting_failed = True
                    spend.save(using=alias, update_fields=["accounting_failed"])
                    continue
                spend.created_at = first_cost_at
                spend.spend = Decimal(sum(receipt.token_cost_microusd or 0 for receipt in receipts)) / 10_000
                if source.is_task:
                    spend.spend += Decimal(4)
                spend.llm_failed_stages = (
                    sorted({receipt.stage for receipt in receipts if receipt.accounting_failed})
                    if not source.is_task
                    else []
                )
                spend.accounting_failed = any(receipt.accounting_failed for receipt in receipts)
                spend.save(using=alias)
        last_id = batch[-1].id


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("signals", "0199_owner_spend"), ("tasks", "0121_squash_2026_09_07_finalize_fks")]
    operations = [migrations.RunPython(backfill_owner_spend, reverse_code=migrations.RunPython.noop)]
