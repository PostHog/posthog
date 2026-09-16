from datetime import datetime

from posthog.dataclasses import frozen


@frozen
class FlagSummary:
    id: int
    key: str
    active: bool
    deleted: bool
    archived: bool
    created_at: datetime
    updated_at: datetime | None
    last_called_at: datetime | None
    status: str
    status_reason: str
    effectively_full_rollout: bool
    max_rollout_percentage: int | None
    variant_keys: tuple[str, ...]
    fully_rolled_out_variant: str | None
