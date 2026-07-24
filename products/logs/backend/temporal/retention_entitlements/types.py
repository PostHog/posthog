from dataclasses import dataclass


@dataclass(frozen=True)
class EnforceLogsRetentionEntitlementsInput:
    dry_run: bool
    batch_size: int = 100


@dataclass(frozen=True)
class EnforceLogsRetentionEntitlementsOutput:
    teams_checked: int
    teams_reset: int
