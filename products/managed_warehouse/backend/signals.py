"""Enqueue a member-teams push to hogtower when what a member can see may have changed.

Each receiver only enqueues, after the transaction commits, and only for an organization with
a managed warehouse. ``member_teams`` reads the committed state when the push runs.

- An organization membership is created, changed (its level) or deleted: that member.
- A user is deactivated: that user, in each of their organizations.
- A role membership is created or deleted: that member.
- A project is created, deleted or moved to another organization, or an access rule on the
  project, on warehouse data or on a property changes: every member of the organization (both,
  for a move). A switch of resolution mode or of entitlement needs no push, because the pushed
  level is capped by a floor that holds under both (``member_teams``).

Access rules and role memberships arrive through the access_control facade, as ids.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save

from posthog.models import OrganizationMembership, Team, User

from products.managed_warehouse.backend import member_teams

# Access rules on these resources change which teams a member sees, or the level on them.
_ACCESS_RESOURCES = frozenset({"project", "property_definition", *member_teams.RESTRICTING_RESOURCES})


def _has_warehouse(organization_id: str) -> bool:
    from products.managed_warehouse.backend.facade.api import has_provisioned_warehouse  # noqa: PLC0415

    return has_provisioned_warehouse(organization_id)


def _on_commit_member(organization_id: object, user_uuid: object) -> None:
    if not member_teams.is_enabled() or organization_id is None or user_uuid is None:
        return
    org, user = str(organization_id), str(user_uuid)

    def enqueue() -> None:
        if _has_warehouse(org):
            member_teams.enqueue_member_push(org, user)

    transaction.on_commit(enqueue)


def _on_commit_organization(organization_id: object) -> None:
    if not member_teams.is_enabled() or organization_id is None:
        return
    org = str(organization_id)

    def enqueue() -> None:
        if _has_warehouse(org):
            member_teams.enqueue_organization_push(org)

    transaction.on_commit(enqueue)


def _user_uuid(user_id: object) -> object:
    return User.objects.filter(pk=user_id).values_list("uuid", flat=True).first()


def _team_organization_id(team_id: object) -> object:
    return Team.objects.filter(pk=team_id).values_list("organization_id", flat=True).first()


def membership_saved(sender: Any, instance: OrganizationMembership, **kwargs: Any) -> None:
    if member_teams.is_enabled():
        _on_commit_member(instance.organization_id, _user_uuid(instance.user_id))


# A receiver that must read state before a write records it on the instance under this name,
# and the receiver after the write enqueues. Outside a transaction on_commit runs at once, so an
# enqueue from before the write could run its push before the write lands.
_PENDING_ATTR = "_managed_warehouse_member_teams_pending"


def membership_deleting(sender: Any, instance: OrganizationMembership, **kwargs: Any) -> None:
    # The user row is still there to read the uuid from, even when the user's own deletion is
    # what removes the membership.
    if member_teams.is_enabled():
        setattr(instance, _PENDING_ATTR, _user_uuid(instance.user_id))


def membership_deleted(sender: Any, instance: OrganizationMembership, **kwargs: Any) -> None:
    user_uuid = getattr(instance, _PENDING_ATTR, None)
    if user_uuid is not None:
        _on_commit_member(instance.organization_id, user_uuid)


def user_saved(sender: Any, instance: User, created: bool = False, **kwargs: Any) -> None:
    # Reactivation needs no push here: the scheduled full push brings the member back.
    if created or instance.is_active or not member_teams.is_enabled():
        return
    for organization_id in OrganizationMembership.objects.filter(user_id=instance.pk).values_list(
        "organization_id", flat=True
    ):
        _on_commit_member(organization_id, instance.uuid)


def team_saving(sender: Any, instance: Team, update_fields: Any = None, **kwargs: Any) -> None:
    # A project moved to another organization: record the old one, whose members lose the team.
    if instance._state.adding or not member_teams.is_enabled():
        return
    if update_fields is not None and not {"organization", "organization_id"} & set(update_fields):
        return
    previous = _team_organization_id(instance.pk)
    if previous is not None and previous != instance.organization_id:
        setattr(instance, _PENDING_ATTR, previous)


def team_saved(sender: Any, instance: Team, created: bool = False, **kwargs: Any) -> None:
    previous = instance.__dict__.pop(_PENDING_ATTR, None)
    if created or previous is not None:
        _on_commit_organization(instance.organization_id)
    if previous is not None:
        _on_commit_organization(previous)


def team_deleted(sender: Any, instance: Team, **kwargs: Any) -> None:
    _on_commit_organization(instance.organization_id)


def access_rule_changed(team_id: int, resource: str) -> None:
    if resource not in _ACCESS_RESOURCES or not member_teams.is_enabled():
        return
    # A rule deleted with its project has no team left to read; team_deleted covers that.
    _on_commit_organization(_team_organization_id(team_id))


def role_membership_changed(user_id: int, organization_id: UUID) -> None:
    _on_commit_member(organization_id, _user_uuid(user_id))


def connect() -> None:
    from products.access_control.backend.facade.api import connect_access_change_receivers  # noqa: PLC0415

    uid = "managed_warehouse_member_teams"
    post_save.connect(membership_saved, sender=OrganizationMembership, dispatch_uid=f"{uid}_membership_saved")
    pre_delete.connect(membership_deleting, sender=OrganizationMembership, dispatch_uid=f"{uid}_membership_deleting")
    post_delete.connect(membership_deleted, sender=OrganizationMembership, dispatch_uid=f"{uid}_membership_deleted")
    post_save.connect(user_saved, sender=User, dispatch_uid=f"{uid}_user_saved")
    pre_save.connect(team_saving, sender=Team, dispatch_uid=f"{uid}_team_saving")
    post_save.connect(team_saved, sender=Team, dispatch_uid=f"{uid}_team_saved")
    post_delete.connect(team_deleted, sender=Team, dispatch_uid=f"{uid}_team_deleted")
    connect_access_change_receivers(
        on_rule_change=access_rule_changed,
        on_role_membership_change=role_membership_changed,
        is_active=member_teams.is_enabled,
        dispatch_uid=uid,
    )
