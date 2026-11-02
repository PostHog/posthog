from dataclasses import dataclass, field

WAREHOUSE_SUGGESTIONS_WORKFLOW_NAME = "warehouse-suggestions"


@dataclass(frozen=True, kw_only=True)
class WarehouseSuggestionsInputs:
    batch_size: int = 25
    max_concurrent: int = 1
    rollout_percentage: float = 1.0
    team_ids: list[int] | None = None


@dataclass(frozen=True, kw_only=True)
class ViewCostRequest:
    team_id: int
    saved_query_id: str


@dataclass(frozen=True, kw_only=True)
class BatchOutcome:
    processed: int = 0
    not_eligible: int = 0
    disabled: int = 0
    failed: int = 0
    view_costs_to_measure: list[ViewCostRequest] = field(default_factory=list)
