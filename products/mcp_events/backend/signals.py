from functools import partial
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Model
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone

from posthog.models import User
from posthog.models.oauth import OAuthApplication, oauth_session_revoked
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


class _RevalidateTeams:
    def __init__(self, team_ids: frozenset[int]) -> None:
        self.team_ids = team_ids
        self.pending = True

    def __call__(self) -> None:
        if not self.pending:
            return
        self.pending = False
        live = (
            MCPEventSubscription.objects.unscoped()
            .filter(team_id__in=self.team_ids, active=True, expires_at__gt=timezone.now())
            .values_list("team_id", flat=True)
            .distinct()
        )
        for team_id in live:
            revalidate_mcp_event_subscriptions.delay(team_id)


def _revalidate_after_commit(team_ids: list[int]) -> None:
    connection = transaction.get_connection()
    pending: set[int] = set()
    # Django removes rolled-back savepoint callbacks, so their deduplication state cannot leak.
    for _, callback, _ in connection.run_on_commit:
        if isinstance(callback, _RevalidateTeams) and callback.pending:
            pending.update(callback.team_ids)
    remaining = frozenset(team_ids) - pending
    if remaining:
        transaction.on_commit(_RevalidateTeams(remaining), robust=True)


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


@receiver(pre_delete, sender=MCPEventSubscription)
def stop_deleted_subscription(
    sender: type[MCPEventSubscription], instance: MCPEventSubscription, **kwargs: Any
) -> None:
    from products.mcp_events.backend.logic.destination import (  # noqa: PLC0415  # Keeps HogQL off the setup path.
        disable_destination,
    )

    disable_destination(instance)


@receiver(pre_delete, sender=User)
def stop_subscriptions_before_user_deletion(sender: type[User], instance: User, **kwargs: Any) -> None:
    from products.mcp_events.backend.logic.revocation import revoke_user  # noqa: PLC0415  # Keeps HogQL off setup.

    revoke_user(user_id=instance.pk)


@receiver(post_save, sender=User)
def stop_subscriptions_of_inactive_user(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    if created or instance.is_active:
        return
    from products.mcp_events.backend.logic.revocation import revoke_user  # noqa: PLC0415  # Keeps HogQL off setup.

    revoke_user(user_id=instance.pk)


@receiver(post_save, sender=OrganizationMembership)
def revalidate_changed_member(
    sender: type[OrganizationMembership], instance: OrganizationMembership, created: bool, **kwargs: Any
) -> None:
    update_fields = kwargs.get("update_fields")
    if created or update_fields is not None and "level" not in update_fields:
        return
    from products.mcp_events.backend.logic.revocation import (  # noqa: PLC0415  # Keeps HogQL off setup.
        revalidate_user_in_organization,
    )

    transaction.on_commit(
        partial(revalidate_user_in_organization, user_id=instance.user_id, organization_id=instance.organization_id)
    )


@receiver(oauth_session_revoked)
def stop_disconnected_oauth_subscriptions(
    sender: type[OAuthApplication], user_id: int | None, application_id: UUID, all_sessions: bool = True, **kwargs: Any
) -> None:
    from products.mcp_events.backend.logic.revocation import (  # noqa: PLC0415  # Keeps HogQL off the setup path.
        recheck_oauth_connection,
        revoke_oauth_application,
    )

    if all_sessions:
        revoke_oauth_application(application_id=application_id, user_id=user_id)
    elif user_id is not None:
        recheck_oauth_connection(application_id=application_id, user_id=user_id)


@receiver(pre_delete, sender=OAuthApplication)
def stop_deleted_oauth_application(sender: type[OAuthApplication], instance: OAuthApplication, **kwargs: Any) -> None:
    from products.mcp_events.backend.logic.revocation import (  # noqa: PLC0415  # Keeps HogQL off the setup path.
        revoke_oauth_application,
    )

    revoke_oauth_application(application_id=instance.pk)


@receiver(post_save, sender=Team)
def revalidate_test_account_filters(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    update_fields = kwargs.get("update_fields")
    if not created and (update_fields is None or "test_account_filters" in update_fields):
        _revalidate_after_commit([instance.pk])


@receiver(post_save, sender="actions.Action")
@receiver(post_delete, sender="actions.Action")
def revalidate_changed_action(sender: type[Model], instance: Any, **kwargs: Any) -> None:
    if not kwargs.get("created", False):
        _revalidate_after_commit([instance.team_id])


@receiver(post_save, sender="cohorts.Cohort")
@receiver(post_delete, sender="cohorts.Cohort")
def revalidate_test_account_cohort(sender: type[Model], instance: Any, **kwargs: Any) -> None:
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"filters", "is_static", "deleted"}.intersection(update_fields):
        return
    if any(
        f.get("type") == "cohort" and f.get("value") == instance.pk
        for f in instance.team.test_account_filters or []
        if isinstance(f, dict)
    ):
        _revalidate_after_commit([instance.team_id])
