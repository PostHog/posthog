from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.models.replay_scanner import ReplayScanner


@frozen
class OnboardingScanner:
    id: UUID
    emits_signals: bool
    can_edit: bool


def has_enabled_onboarding_scanners(team: Team) -> bool:
    return ReplayScanner.objects.filter(team_id=team.id, enabled=True).exists()


def enabled_onboarding_scanners(team: Team, user: User) -> tuple[OnboardingScanner, ...]:
    access = UserAccessControl(user=user, team=team)
    scanners = access.filter_queryset_by_access_level(
        ReplayScanner.objects.filter(team_id=team.id, enabled=True).order_by("id"), resource="replay_scanner"
    )
    return tuple(
        OnboardingScanner(
            id=scanner.id,
            emits_signals=scanner.emits_signals,
            can_edit=access.check_access_level_for_object(scanner, "editor"),
        )
        for scanner in scanners[:101]
    )


def enable_onboarding_scanner_signals(
    team: Team, user: User, scanner_ids: Sequence[UUID], *, credential_can_write: bool
) -> None:
    if not scanner_ids:
        return
    access = UserAccessControl(user=user, team=team)
    scanners = list(ReplayScanner.objects.select_for_update().filter(team_id=team.id, id__in=scanner_ids, enabled=True))
    if {scanner.id for scanner in scanners} != set(scanner_ids):
        raise ValueError("The available replay scanners changed. Review activation again.")
    if any(not access.check_access_level_for_object(scanner, "viewer") for scanner in scanners):
        raise PermissionError("You no longer have access to a selected replay scanner.")
    if any(not scanner.emits_signals for scanner in scanners) and not credential_can_write:
        raise PermissionError("This credential cannot configure replay scanner findings.")
    if any(not scanner.emits_signals for scanner in scanners) and not access.check_access_level_for_resource(
        "session_recording", "viewer"
    ):
        raise PermissionError("Configuring a Replay Vision scanner requires session recording read access.")
    for scanner in scanners:
        if not scanner.emits_signals:
            if not access.check_access_level_for_object(scanner, "editor"):
                raise PermissionError("You need editor access to enable this replay scanner's findings.")
            scanner.emits_signals = True
            scanner.save(update_fields=["emits_signals", "updated_at"])
