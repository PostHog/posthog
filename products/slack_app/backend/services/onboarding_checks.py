"""Workspace and person checks shared by the onboarding thread and the old installer DM."""

from posthog.integrations import IntegrationManager
from posthog.models import OrganizationMembership, Team
from posthog.models.organization import Organization
from posthog.models.user_integration import UserIntegration


def has_team_github(team_id: int) -> bool:
    return IntegrationManager.github.oauth.exists(team_id)


def has_personal_github(user_id: int) -> bool:
    return UserIntegration.objects.filter(user_id=user_id, kind=UserIntegration.IntegrationKind.GITHUB).exists()


def has_ai_approval(team_id: int) -> bool:
    org_approved = (
        Team.objects.filter(id=team_id).values_list("organization__is_ai_data_processing_approved", flat=True).first()
    )
    return bool(org_approved)


def is_org_admin(user_id: int, team_id: int) -> bool:
    """Whether the user can toggle org settings (AI consent needs ADMIN+)."""
    org_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    level = (
        OrganizationMembership.objects.filter(organization_id=org_id, user_id=user_id)
        .values_list("level", flat=True)
        .first()
    )
    return level is not None and level >= OrganizationMembership.Level.ADMIN


def has_enabled_source(team_id: int) -> bool:
    from products.signals.backend.facade.api import (
        has_enabled_source as signals_has_enabled_source,  # noqa: PLC0415 — keeps the signals stack off the slack import path
    )

    return signals_has_enabled_source(team_id)


def approve_ai_data_processing_for_team(team_id: int) -> bool:
    """Set the org consent for the team's organization. The caller checks that the person is an org admin."""
    org_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    organization = Organization.objects.filter(id=org_id).first() if org_id is not None else None
    if organization is None:
        return False
    # Save the instance (not a queryset .update()) so ModelActivityMixin records the consent change
    # in the activity log and updated_at is bumped.
    organization.is_ai_data_processing_approved = True
    organization.save(update_fields=["is_ai_data_processing_approved", "updated_at"])
    return True
