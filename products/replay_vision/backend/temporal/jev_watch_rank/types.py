from pydantic import BaseModel


class JevWatchRankSweepInputs(BaseModel, frozen=True):
    pass


class JevWatchRankSweepResult(BaseModel, frozen=True):
    teams_seen: int = 0
    teams_enrolled: int = 0
    scanners_judged: int = 0
    observations_judged: int = 0
    failed_chunks: int = 0
    input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    hit_scanner_cap: bool = False
