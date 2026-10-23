from decimal import Decimal
from uuid import UUID

from django.db import migrations, transaction


def backfill_owner_spend(apps, schema_editor):
    Source = apps.get_model("signals", "LegacySignalSpend")
    Spend = apps.get_model("signals", "SignalSpend")
    Scout = apps.get_model("signals", "SignalScoutRun")
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
                owner = {"signal_id": source.signal_id} if source.signal_id else {"scout_run_id": source.scout_run_id}
                spend, _ = Spend._base_manager.using(alias).get_or_create(
                    team_id=source.team_id,
                    **owner,
                )
                spend = Spend._base_manager.using(alias).select_for_update().get(id=spend.id)
                if spend.finalized_at is not None:
                    continue
                if source.is_task and UUID(source.source_id) not in spend.task_run_ids:
                    spend.task_run_ids.append(UUID(source.source_id))
                receipts = list(Source._base_manager.using(alias).filter(team_id=source.team_id, **owner))
                first_cost_at = min(receipt.created_at for receipt in receipts)
                if spend.signal_id and spend.created_at < first_cost_at:
                    spend.accounting_failed = True
                    spend.save(using=alias, update_fields=["accounting_failed"])
                    continue
                spend.created_at = first_cost_at
                if source.scout_run_id:
                    scout_started = (
                        Scout._base_manager.using(alias)
                        .filter(id=source.scout_run_id, team_id=source.team_id)
                        .values_list("created_at", flat=True)
                        .first()
                    )
                    if scout_started is not None:
                        spend.created_at = min(spend.created_at, scout_started)
                spend.spend = Decimal(sum(receipt.token_cost_microusd or 0 for receipt in receipts)) / 10_000
                spend.spend += Decimal(4) * sum(receipt.is_task for receipt in receipts)
                spend.accounting_failed = bool(spend.llm_failed_stages) or any(
                    receipt.accounting_failed for receipt in receipts
                )
                spend.finalized_at = None
                spend.save(using=alias)
        last_id = batch[-1].id


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("signals", "0198_owner_spend"), ("tasks", "0121_squash_2026_09_07_finalize_fks")]
    operations = [migrations.RunPython(backfill_owner_spend, reverse_code=migrations.RunPython.noop)]
