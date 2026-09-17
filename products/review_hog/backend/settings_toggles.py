"""Bulk on/off for the per-user boolean toggles on `ReviewUserSettings`.

The inbox toggles (`review_inbox_prs`, `stamphog_review_inbox_prs`) default to off per user because
they are the budget gate for 100%-coverage review cost, and `resolve_comments` defaults to on
because reviewing includes resolving. Flipping any of them for a whole team is a deliberate operator
action rather than a default change. The `enable_*` / `disable_*` management commands are thin
wrappers over `plan_toggle` + `apply_toggle`: one toggle, one direction, for every active member of
the team's organization or for an explicit list of user ids. Other fields on existing rows are
untouched, users can still change the toggle in the Code review settings afterwards, and members
who join later keep the default until a command is re-run.
"""

from collections.abc import Sequence
from typing import Literal

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team

from products.review_hog.backend.models import ReviewUserSettings

ToggleField = Literal["review_inbox_prs", "stamphog_review_inbox_prs", "resolve_comments"]


def toggle_default(field: ToggleField) -> bool:
    return bool(ReviewUserSettings._meta.get_field(field).get_default())


class UsersNotInOrganization(ValueError):
    def __init__(self, team_id: int, user_ids: Sequence[int]) -> None:
        self.user_ids = tuple(user_ids)
        ids = ", ".join(str(user_id) for user_id in self.user_ids)
        super().__init__(f"user id(s) {ids} are not members of the organization that owns team {team_id}")


@frozen
class TogglePlan:
    team_id: int
    field: ToggleField
    enabled: bool
    target_count: int
    # Users with no row yet. Empty when the requested value is the field's default, because a
    # missing row already reads as the default.
    to_create: tuple[int, ...]
    to_flip: tuple[int, ...]

    @property
    def changed_user_ids(self) -> tuple[int, ...]:
        return self.to_create + self.to_flip

    @property
    def already_set(self) -> int:
        return self.target_count - len(self.changed_user_ids)

    @property
    def summary(self) -> str:
        verb = "enable" if self.enabled else "disable"
        return (
            f"team {self.team_id}, {self.field}: {self.target_count} target user(s), "
            f"{len(self.to_create)} row(s) to create, {len(self.to_flip)} existing row(s) to {verb}, "
            f"{self.already_set} already {verb}d"
        )


def plan_toggle(
    *, team_id: int, field: ToggleField, enabled: bool, user_ids: Sequence[int] | None = None
) -> TogglePlan:
    """Work out which `ReviewUserSettings` rows a bulk toggle change touches, without writing.

    Raises `TeamScopeError` / `Team.DoesNotExist` for a bad team id and `UsersNotInOrganization`
    when an explicit id is not a member of the team's organization, so a typo fails loudly instead
    of silently changing nothing.
    """
    # Environment ids resolve to the root team, mirroring the settings API: the rows must land
    # on the same team the workflow's `ReviewUserSettings.load` reads them from.
    team_id = resolve_effective_team_id(team_id)
    team = Team.objects.get(id=team_id)
    memberships = OrganizationMembership.objects.filter(organization_id=team.organization_id)
    if user_ids is None:
        target_ids = list(memberships.filter(user__is_active=True).values_list("user_id", flat=True))
    else:
        target_ids = list(dict.fromkeys(user_ids))
        member_ids = set(memberships.filter(user_id__in=target_ids).values_list("user_id", flat=True))
        unknown = [user_id for user_id in target_ids if user_id not in member_ids]
        if unknown:
            raise UsersNotInOrganization(team_id, unknown)

    existing = {
        row.user_id: row
        for row in ReviewUserSettings.objects.for_team(team_id, canonical=True).filter(user_id__in=target_ids)
    }
    to_flip = tuple(
        user_id for user_id in target_ids if user_id in existing and getattr(existing[user_id], field) is not enabled
    )
    missing = tuple(user_id for user_id in target_ids if user_id not in existing)
    to_create = missing if enabled is not toggle_default(field) else ()
    return TogglePlan(
        team_id=team_id,
        field=field,
        enabled=enabled,
        target_count=len(target_ids),
        to_create=to_create,
        to_flip=to_flip,
    )


def apply_toggle(plan: TogglePlan) -> None:
    rows = ReviewUserSettings.objects.for_team(plan.team_id, canonical=True)
    with transaction.atomic():
        to_flip = list(rows.filter(user_id__in=plan.to_flip))
        for user_id in plan.to_create:
            # get_or_create because a settings GET auto-creates rows with the model defaults: a
            # user opening the Code review tab between the plan and this write must end at the
            # requested value, not crash the run on the unique (team, user) constraint.
            row, created = rows.get_or_create(
                team_id=plan.team_id, user_id=user_id, defaults={plan.field: plan.enabled}
            )
            if not created:
                to_flip.append(row)
        for row in to_flip:
            setattr(row, plan.field, plan.enabled)
            row.save(update_fields=[plan.field, "updated_at"])
