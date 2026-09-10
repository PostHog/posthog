from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from django.core.cache import cache

import structlog

CostStage = Literal["research", "implementation"]
COST_INGESTION_GRACE_SECONDS = 300
_COST_STAGES: tuple[CostStage, ...] = ("research", "implementation")

logger = structlog.get_logger(__name__)


def normalise_cost(model: str, spend: Decimal) -> Decimal:
    return spend


def add_cost(costs: dict[CostStage, Decimal], stage: CostStage, model: str, spend: Decimal) -> None:
    costs[stage] = costs.get(stage, Decimal(0)) + normalise_cost(model, spend)


def costs_in_cents(costs: dict[CostStage, Decimal]) -> dict[str, int]:
    # Round the sum, not each generation: small calls must still contribute to the total.
    return {
        stage: int((costs.get(stage, Decimal(0)) * 100).to_integral_value(rounding=ROUND_HALF_EVEN))
        for stage in _COST_STAGES
    }


def schedule_signal_cost_update(team_id: int, signal_id: str, *, raise_on_error: bool = False) -> None:
    try:
        from products.signals.backend.tasks import refresh_signal_costs  # noqa: PLC0415 - avoids a task import cycle

        key = f"signal-cost-update:{team_id}:{signal_id}"
        if cache.add(key, True, timeout=60):
            try:
                refresh_signal_costs.apply_async(
                    kwargs={"team_id": team_id, "signal_id": signal_id}, countdown=COST_INGESTION_GRACE_SECONDS
                )
            except Exception:
                cache.delete(key)
                raise
    except Exception:
        logger.exception("signals.cost_update_schedule_failed", team_id=team_id, signal_id=signal_id)
        if raise_on_error:
            raise
