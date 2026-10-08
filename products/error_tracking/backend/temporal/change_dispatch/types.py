import dataclasses


@dataclasses.dataclass(frozen=True)
class ChangeDispatchInputs:
    # Below the one-minute schedule interval, so a run finishes before the next one is due.
    time_budget_seconds: int = 50


@dataclasses.dataclass(frozen=True)
class ChangeDispatchResult:
    dispatched: int
    delivered: int
    undelivered: int
    dropped: int
