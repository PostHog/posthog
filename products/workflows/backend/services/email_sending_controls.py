"""Staff controls over a team's workflow email sending: suspension and the pinned trust tier."""

from django.db import transaction
from django.utils import timezone

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.user import User

from products.workflows.backend.facade.contracts import EmailSendingState, EmailSendingSuspensionChange
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.utils.email_sending_tiers import MIN_EMAIL_SENDING_TIER


def ensure_workflows_config(team_id: int) -> None:
    get_or_create_team_extension(Team.objects.get(pk=team_id), TeamWorkflowsConfig)


def get_email_sending_state(team_id: int) -> EmailSendingState | None:
    config = TeamWorkflowsConfig.objects.filter(team_id=team_id).first()
    if config is None:
        return None
    return EmailSendingState(
        suspended_at=config.email_sending_suspended_at,
        suspension_reason=config.email_sending_suspension_reason,
        tier=config.email_sending_tier,
        tier_pinned=config.email_sending_tier_pinned,
        tier_updated_at=config.email_sending_tier_updated_at,
    )


def suspend_email_sending(
    team_id: int, reason: str, *, user_id: int | None = None, was_impersonated: bool = False
) -> EmailSendingSuspensionChange:
    # Row-lock the config while checking + flipping so two concurrent submits (retried POST,
    # two open admin tabs) can't both pass the idempotency check and both dispatch the
    # customer email + notification. Side effects stay with the caller, outside the atomic block.
    ensure_workflows_config(team_id)
    with transaction.atomic():
        config = TeamWorkflowsConfig.objects.select_for_update().get(team_id=team_id)
        if config.email_sending_suspended_at is not None:
            return EmailSendingSuspensionChange(
                changed_at=None, previously_suspended_at=config.email_sending_suspended_at
            )
        previous_tier = config.email_sending_tier
        suspended_at = timezone.now()
        config.email_sending_suspended_at = suspended_at
        config.email_sending_suspension_reason = reason
        # Drop the trust tier now, in the same locked transaction, rather than at the next
        # daily sweep: a suspension is the strongest signal there is, and the tier sets how
        # fast the team may send once reinstated. A suspension always maps to the lowest
        # tier, and that mapping needs no metrics, so write it here instead of through the
        # recompute. This does not depend on ClickHouse and it also covers pinned teams,
        # which the periodic sweep skips.
        config.email_sending_tier = MIN_EMAIL_SENDING_TIER
        config.email_sending_tier_updated_at = suspended_at
        config.save(
            update_fields=[
                "email_sending_suspended_at",
                "email_sending_suspension_reason",
                "email_sending_tier",
                "email_sending_tier_updated_at",
            ]
        )
        _log_tier_change(
            team_id,
            previous_tier=previous_tier,
            new_tier=MIN_EMAIL_SENDING_TIER,
            reason="staff_suspension",
            user_id=user_id,
            was_impersonated=was_impersonated,
        )
    return EmailSendingSuspensionChange(changed_at=suspended_at)


def unsuspend_email_sending(team_id: int) -> EmailSendingSuspensionChange:
    # Symmetric to suspend: lock the row, re-check, flip inside the transaction so racing
    # submits can't both fire the re-enable side effects.
    with transaction.atomic():
        config = TeamWorkflowsConfig.objects.select_for_update().filter(team_id=team_id).first()
        if not config or config.email_sending_suspended_at is None:
            return EmailSendingSuspensionChange(changed_at=None)
        unsuspended_at = timezone.now()
        config.email_sending_suspended_at = None
        config.email_sending_suspension_reason = ""
        config.save(update_fields=["email_sending_suspended_at", "email_sending_suspension_reason"])
    return EmailSendingSuspensionChange(changed_at=unsuspended_at)


def set_email_sending_tier(
    team_id: int, *, tier: int, pinned: bool, user_id: int | None = None, was_impersonated: bool = False
) -> int:
    """Write a staff-chosen tier and pin state, and return the tier the team had before."""
    ensure_workflows_config(team_id)
    with transaction.atomic():
        config = TeamWorkflowsConfig.objects.select_for_update().get(team_id=team_id)
        previous_tier = config.email_sending_tier
        previous_pinned = config.email_sending_tier_pinned
        config.email_sending_tier = tier
        config.email_sending_tier_pinned = pinned
        if tier != previous_tier:
            # Only a real tier change restarts the dwell clock. Toggling the pin alone must not
            # push the next earned promotion out by the full dwell.
            config.email_sending_tier_updated_at = timezone.now()
        config.save(
            update_fields=[
                "email_sending_tier",
                "email_sending_tier_pinned",
                "email_sending_tier_updated_at",
            ]
        )
        _log_tier_change(
            team_id,
            previous_tier=previous_tier,
            new_tier=tier,
            previous_pinned=previous_pinned,
            pinned=pinned,
            user_id=user_id,
            was_impersonated=was_impersonated,
        )
    return previous_tier


def _log_tier_change(
    team_id: int,
    *,
    previous_tier: int,
    new_tier: int,
    reason: str = "",
    previous_pinned: bool | None = None,
    pinned: bool | None = None,
    user_id: int | None,
    was_impersonated: bool,
) -> None:
    # Deferred because the tier module pulls the ClickHouse metrics client, and this module sits on
    # the facade import path, which django.setup() walks.
    from products.workflows.backend.services.email_sending_tier import log_email_sending_tier_change  # noqa: PLC0415

    team = Team.objects.get(pk=team_id)
    log_email_sending_tier_change(
        team_id=team_id,
        team_name=team.name,
        organization_id=team.organization_id,
        previous_tier=previous_tier,
        new_tier=new_tier,
        reason=reason,
        previous_pinned=previous_pinned,
        pinned=pinned,
        user=User.objects.filter(pk=user_id).first() if user_id is not None else None,
        was_impersonated=was_impersonated,
    )
