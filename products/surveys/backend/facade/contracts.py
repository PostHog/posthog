from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class SurveySummary:
    id: UUID
    name: str
    created_at: datetime
    start_date: datetime | None
    end_date: datetime | None
    linked_flag_id: int | None
    archived: bool
