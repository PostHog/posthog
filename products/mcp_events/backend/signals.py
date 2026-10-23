from functools import partial
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team

from products.mcp_events.backend.models import MCPEventSubscription
from products.mcp_events.backend.tasks.tasks import revalidate_mcp_event_subscriptions

# Access control models are referenced by label so this module does not import the access_control internals.
ACCESS_RULE_SENDERS = ("ee.AccessControl", "access_control.PropertyAccessControl")
ROLE_MEMBERSHIP_SENDER = "ee.RoleMembership"


@receiver(post_delete, sender=PersonalAPIKey)
def revoke_subscriptions_of_deleted_key(sender: type[PersonalAPIKey], instance: PersonalAPIKey, **kwargs: Any) -> None:
    from products.mcp_events.backend.logic import revocation  # noqa: PLC0415 — keeps HogQL off the setup path

    revocation.revoke_personal_api_key(user_id=instance.user_id, key_id=instance.pk)


@receiver(post_save, sender=PersonalAPIKey)
def recheck_subscriptions_of_changed_key(
    sender: type[PersonalAPIKey], instance: PersonalAPIKey, created: bool, **kwargs: Any
) -> None:
    update_fields = kwargs.get("update_fields")
    # Authentication stamps last_used_at on every use, which changes nothing a subscription depends on.
    if created or (update_fields is not None and set(update_fields) == {"last_used_at"}):
        return
    from products.mcp_events.backend.logic import revocation  # noqa: PLC0415 — keeps HogQL off the setup path

    revocation.recheck_personal_api_key(instance)


@receiver(post_delete, sender=OrganizationMembership)
def revoke_subscriptions_of_removed_member(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: Any
) -> None:
    from products.mcp_events.backend.logic import revocation  # noqa: PLC0415 — keeps HogQL off the setup path

    revocation.revoke_user_in_organization(user_id=instance.user_id, organization_id=instance.organization_id)


def _revalidate_after_commit(team_ids: list[int]) -> None:
    live = (
        MCPEventSubscription.objects.unscoped()
        .filter(team_id__in=team_ids, active=True, expires_at__gt=timezone.now())
        .values_list("team_id", flat=True)
        .distinct()
    )
    for team_id in live:
        transaction.on_commit(partial(revalidate_mcp_event_subscriptions.delay, team_id))


def revalidate_after_access_rule_change(sender: type[Model], instance: Any, **kwargs: Any) -> None:
    _revalidate_after_commit([instance.team_id])


def revalidate_after_role_membership_change(sender: type[Model], instance: Any, **kwargs: Any) -> None:
    try:
        organization_id = instance.role.organization_id
    except ObjectDoesNotExist:
        return
    _revalidate_after_commit(list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True)))


for _sender in ACCESS_RULE_SENDERS:
    post_save.connect(revalidate_after_access_rule_change, sender=_sender, dispatch_uid=f"mcp_events_save_{_sender}")
    post_delete.connect(
        revalidate_after_access_rule_change, sender=_sender, dispatch_uid=f"mcp_events_delete_{_sender}"
    )
post_save.connect(revalidate_after_role_membership_change, sender=ROLE_MEMBERSHIP_SENDER)
post_delete.connect(revalidate_after_role_membership_change, sender=ROLE_MEMBERSHIP_SENDER)
