from uuid import UUID

from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task

from posthog.llm.gateway_client import resolve_ai_gateway_config
from posthog.llm.gateway_usage import fetch_gateway_cost

from products.signals.backend.models import SignalSpend
from products.signals.backend.spend import record_llm_spend, refresh_task_spend
from products.tasks.backend.facade.billing import process_pending_gateway_usage

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def recover_spend(team_id: int, spend_id: str) -> None:
    spend = SignalSpend.objects.for_team(team_id).filter(id=spend_id).first()
    if spend is None:
        return
    gateway = resolve_ai_gateway_config()
    for source_id, source in spend.trial_sources.items():
        if not source.get("actual_cost_incomplete", source["accounting_failed"]):
            continue
        try:
            if source["is_task"]:
                run_id = source_id.removeprefix("task:")
                environment_id = source.get("environment_id", team_id)
                process_pending_gateway_usage(run_id=UUID(run_id), team_id=environment_id)
                refresh_task_spend(team_id=environment_id, run_id=run_id)
            elif gateway and source.get("request_id"):
                cost = async_to_sync(fetch_gateway_cost)(
                    source["request_id"],
                    base_url=gateway.url,
                    api_key=gateway.api_key,
                )
                if cost is not None:
                    record_llm_spend(
                        source["request_id"],
                        token_cost_microusd=cost.cost_microusd,
                        team_id=team_id,
                        signal_id=str(spend.signal_id),
                        stage=source["stage"],
                        source_id=source_id,
                    )
        except Exception:
            logger.exception("signals.spend.recovery_failed", team_id=team_id, spend_id=spend_id)
    SignalSpend.objects.for_team(team_id).filter(id=spend_id).update(updated_at=timezone.now())


@shared_task(ignore_result=True)
def recover_incomplete_spend() -> None:
    for spend in (
        SignalSpend.objects.unscoped().filter(accounting_failed=True).order_by("updated_at").only("id", "team_id")[:100]
    ):
        recover_spend.apply_async(args=(spend.team_id, str(spend.id)), expires=60)
