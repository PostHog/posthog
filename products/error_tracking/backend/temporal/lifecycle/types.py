import dataclasses


@dataclasses.dataclass(frozen=True)
class LifecycleIssueSnapshot:
    name: str | None
    description: str | None
    status: str
    created_at: str
