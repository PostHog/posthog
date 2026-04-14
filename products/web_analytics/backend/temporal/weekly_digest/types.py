import dataclasses


@dataclasses.dataclass
class WAWeeklyDigestInput:
    """Top-level input for the WA weekly digest coordinator workflow."""

    dry_run: bool = False


@dataclasses.dataclass
class BuildAndSendDigestForOrgInput:
    """Input for the per-org activity."""

    org_id: str
    dry_run: bool = False


@dataclasses.dataclass
class SendTestDigestInput:
    """Input for the test activity: send a single digest for one team."""

    team_id: int
    email: str
    force: bool = False
