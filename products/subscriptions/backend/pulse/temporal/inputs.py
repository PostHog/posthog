from datetime import datetime
from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class ProactiveDispatchSnapshot:
    version: int
    enabled: bool
    config_snapshot_ref: str
    wall_clock_budget_seconds: int = 0
    finalization_margin_seconds: int = 0


@frozen
class PulseStartInput:
    team_id: int
    subscription_id: int
    delivery_id: UUID
    report_snapshot_ref: str
    proactive_snapshot: ProactiveDispatchSnapshot


@frozen
class PulseWorkflowInput:
    team_id: int
    subscription_id: int
    delivery_id: UUID
    pulse_run_id: UUID
    report_snapshot_ref: str
    deadline: datetime
    proactive_snapshot: ProactiveDispatchSnapshot


@frozen
class PulseWorkflowResult:
    pulse_run_id: UUID
    status: str
    result_ref: str
    failure_code: str | None = None


@frozen
class PulseDeliveryBundleInput:
    team_id: int
    pulse_run_id: UUID
    destination: str
    failure_code: str | None = None
    subscription_id: int | None = None
    delivery_id: UUID | None = None
    report_snapshot_ref: str | None = None
    config_snapshot_ref: str | None = None


@frozen
class PulseDeliveryBundleRef:
    ledger_id: UUID
