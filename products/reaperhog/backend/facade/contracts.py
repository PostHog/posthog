from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class ScanRequest:
    team_id: int
    repository: str
    scope: str
    repo_path: str


@dataclass(frozen=True)
class ScanSummary:
    inventory_id: str
    head_sha: str
    hit_count: int
    cluster_count: int
    strong_count: int
    note: str
