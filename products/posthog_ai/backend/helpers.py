"""Shared helpers for the PostHog AI sandbox-runtime services."""

from posthog.models import Team, User


class BaseSandboxService:
    """Shared base for the sandbox-runtime services that act on behalf of a user.

    Holds the team/user the services operate against; extension point for any future
    shared behavior.
    """

    def __init__(self, team: Team, user: User) -> None:
        self.team = team
        self.user = user
