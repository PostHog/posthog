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
    """Input for the test activity.

    Two modes:
    - email only: send the user's full real digest (one email per org they're in)
    - email + team_id: preview that single team's digest as if the user were receiving it

    Bypasses notification settings and feature flags. Always enforces org membership
    and team access.
    """

    email: str
    team_id: int | None = None
