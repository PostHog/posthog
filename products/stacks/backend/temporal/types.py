from dataclasses import dataclass


@dataclass(frozen=True)
class StackRunInput:
    team_id: int
    diff_id: str
    # Set for a push: the attempt the lease was taken for.
    attempt_id: str | None = None


@dataclass(frozen=True)
class StackCleanupInput:
    pass
