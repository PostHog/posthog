import dataclasses


@dataclasses.dataclass(frozen=True)
class AutoResolveInputs:
    # Teams per batch activity. Each team runs its own candidate query and resolve transactions.
    batch_size: int = 50


@dataclasses.dataclass(frozen=True)
class AutoResolveTeamsInputs:
    team_ids: list[int]


@dataclasses.dataclass(frozen=True)
class AutoResolveTeamsResult:
    teams_processed: int
    teams_failed: int
    issues_resolved: int


@dataclasses.dataclass(frozen=True)
class AutoResolveResult:
    teams_total: int
    teams_failed: int
    issues_resolved: int
