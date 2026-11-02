from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from products.signals.backend import spend_billing


def get_signals_spend_billing_credits_by_team(
    begin: datetime,
    end: datetime,
    organization_id: str | UUID | None = None,
    organization_ids: Collection[str | UUID] | None = None,
) -> list[tuple[int, int]]:  # nosemgrep: tuple-return-prefer-dataclass — usage-counter contract
    return spend_billing.get_signals_spend_billing_credits_by_team(begin, end, organization_id, organization_ids)


def task_run_uses_usage_billing(*, team_id: int, organization_id: UUID, run_id: UUID) -> bool:
    return spend_billing.task_run_uses_usage_billing(team_id=team_id, organization_id=organization_id, run_id=run_id)
