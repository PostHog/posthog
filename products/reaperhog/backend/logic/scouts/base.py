from collections.abc import Iterable
from datetime import datetime
from functools import cached_property
from typing import Protocol

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.reaperhog.backend.facade.enums import NAMED_SCOPES, ScoutName
from products.reaperhog.backend.logic.artefacts import Hit
from products.reaperhog.backend.logic.repo import RepoIndex

_NOREPLY_SUFFIX = "@users.noreply.github.com"


@frozen(slots=False)
class ScoutContext:
    team_id: int
    repo: RepoIndex
    scope: str
    now: datetime

    @property
    def scope_path(self) -> str | None:
        return None if self.scope in NAMED_SCOPES else self.scope.strip("/")

    def in_scope(self, files: Iterable[str]) -> bool:
        path = self.scope_path
        if path is None:
            return True
        prefix = f"{path}/"
        return any(file == path or file.startswith(prefix) for file in files)

    @cached_property
    def org_emails(self) -> frozenset[str]:
        organization_id = Team.objects.get(id=self.team_id).organization_id
        emails = User.objects.filter(
            organization_membership__organization_id=organization_id, is_active=True
        ).values_list("email", flat=True)
        return frozenset(email.lower() for email in emails)

    def author_left(self, email: str) -> bool | None:
        normalized = email.lower()
        if normalized.endswith(_NOREPLY_SUFFIX) or not self.org_emails:
            return None
        return normalized not in self.org_emails


class Scout(Protocol):
    name: ScoutName

    def applies_to(self, scope: str) -> bool: ...

    def run(self, context: ScoutContext) -> list[Hit]: ...


def flag_patterns(key: str, constant: str | None) -> list[str]:
    patterns = [f"'{key}'", f'"{key}"']
    if constant:
        patterns.append(f"FEATURE_FLAGS.{constant}")
    return patterns


def days_between(now: datetime, then: datetime) -> int:
    return (now - then).days
