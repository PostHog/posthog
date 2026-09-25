from pydantic import BaseModel


class JevWatchRankSweepInputs(BaseModel, frozen=True):
    pass


class JevWatchRankSweepResult(BaseModel, frozen=True):
    # True when this region serves no decisions at all, in which case every other count is zero.
    decisions_unavailable: bool = False
    teams_seen: int = 0
    teams_enrolled: int = 0
    # Enrolled in the flag, but the organization has not approved AI data processing.
    teams_without_consent: int = 0
    scanners_judged: int = 0
    # Windows whose membership matched the cache's fingerprint, so no Jev call was spent.
    scanners_skipped_unchanged: int = 0
    observations_judged: int = 0
    failed_chunks: int = 0
    input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    hit_team_cap: bool = False
    hit_scanner_cap: bool = False
    hit_time_budget: bool = False
