"""Workspace and person checks shared by the onboarding steps and the old installer DM."""

from django.db import transaction

import structlog

from posthog.integrations import IntegrationManager
from posthog.models import OrganizationMembership, Team
from posthog.models.organization import Organization
from posthog.models.user_integration import UserIntegration

logger = structlog.get_logger(__name__)


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
        OrganizationMembership.objects.with_effective_level()
        .filter(organization_id=org_id, user_id=user_id)
        .values_list("resolved_level", flat=True)
        .first()
    )
    return level is not None and level >= OrganizationMembership.Level.ADMIN


def has_enabled_source(team_id: int) -> bool:
    from products.signals.backend.facade.api import (
        has_enabled_source as signals_has_enabled_source,  # noqa: PLC0415 — keeps the signals stack off the slack import path
    )

    return signals_has_enabled_source(team_id)


def enabled_source_keys(team_id: int) -> list[str]:
    from products.signals.backend.facade.api import (
        onboarding_sources,  # noqa: PLC0415 — keeps the signals stack off the slack import path
    )

    return [source.key for source in onboarding_sources(team_id) if source.enabled]


def is_ai_data_processing_locked(team_id: int) -> bool:
    return Team.objects.filter(id=team_id, organization__is_ai_data_processing_locked=True).exists()


def approve_ai_data_processing_for_team(team_id: int) -> bool:
    """Set the org consent for the team's organization. The caller checks that the person is an org admin.
    Returns False when the organization is gone or support has locked AI data processing off."""
    org_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if org_id is None:
        return False
    with transaction.atomic():
        # nosemgrep: hot-parent-row-select-for-update -- the organization row is the resource being changed
        organization = Organization.objects.select_for_update().filter(id=org_id).first()
        if organization is None or organization.is_ai_data_processing_locked:
            return False
        # Save the instance (not a queryset .update()) so ModelActivityMixin records the consent change
        # in the activity log and updated_at is bumped.
        organization.is_ai_data_processing_approved = True
        organization.save(update_fields=["is_ai_data_processing_approved", "updated_at"])
    return True


def out_of_ai_credits(team_id: int) -> bool:
    """Nobody asked for a work focus, so a team without AI credits gets no run and no message about it."""
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps the billing query stack off the Slack import path
        is_team_over_ai_credit_budget,
    )

    api_token = Team.objects.filter(id=team_id).values_list("api_token", flat=True).first()
    if not api_token:
        return False
    try:
        return is_team_over_ai_credit_budget(api_token)
    except Exception:
        # The quota cache reads Redis. An outage must not stop the runs of teams that have credits.
        logger.warning("slack_app_daily_focus_ai_credit_check_failed", team_id=team_id, exc_info=True)
        return False
