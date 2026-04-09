from dataclasses import dataclass


@dataclass
class WebNotableChangesCoordinatorInput:
    batch_size: int = 100
    limit_per_team: int = 10


@dataclass
class ProcessTeamBatchInput:
    team_ids: list[int]
    week_key: str
    week_start_iso: str
    limit_per_team: int = 10
