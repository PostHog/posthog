from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from django.db.models import BooleanField, Case, ExpressionWrapper, IntegerField, Q, QuerySet, Value, When

from posthog.dataclasses import frozen
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.api import allowed_saved_query_ids, backing_table_ids_by_saved_query
from products.warehouse_sources.backend.facade.api import allowed_table_ids

from ..facade.contracts import SubjectKinds
from ..facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
    WarehouseSuggestionSurface,
)
from ..models import WarehouseSuggestion
from .flags import is_warehouse_suggestions_enabled
from .rules import RULES

if TYPE_CHECKING:
    from posthog.models import Team

    from products.access_control.backend.facade.user_access_control import AccessControlLevel


class AllowedSubjectIds(Protocol):
    def __call__(
        self,
        team_id: int,
        user_access_control: "UserAccessControl",
        *,
        required_level: "AccessControlLevel" = ...,
        ids: Collection[UUID] | None = ...,
    ) -> frozenset[UUID]: ...


ALLOWED_SUBJECT_IDS: Mapping[WarehouseSuggestionSubjectKind, AllowedSubjectIds] = {
    WarehouseSuggestionSubjectKind.SAVED_QUERY: allowed_saved_query_ids,
    WarehouseSuggestionSubjectKind.TABLE: allowed_table_ids,
}
CATALOG_KINDS = frozenset({WarehouseSuggestionKind.CERTIFY, WarehouseSuggestionKind.DEPRECATE})
EDITOR_LEVEL: "AccessControlLevel" = "editor"
SURFACE_FILTERS: Mapping[WarehouseSuggestionSurface, Q] = {
    WarehouseSuggestionSurface.MODELS: Q(
        kind__in=[WarehouseSuggestionKind.MATERIALIZE, WarehouseSuggestionKind.UNMATERIALIZE]
    )
    | Q(kind=WarehouseSuggestionKind.DEPRECATE, subject_kind=WarehouseSuggestionSubjectKind.SAVED_QUERY),
    WarehouseSuggestionSurface.CATALOG: Q(kind__in=CATALOG_KINDS),
}


def surface_q(surface: WarehouseSuggestionSurface | None) -> Q:
    return Q() if surface is None else SURFACE_FILTERS[surface]


def actionable_waiting(
    team_id: int,
    user_access_control: "UserAccessControl",
    surface: WarehouseSuggestionSurface | None,
    subject_kinds: SubjectKinds,
) -> Q:
    """Waiting suggestions on `surface`, or of every kind without one, the user could accept or dismiss once shown."""
    kinds = subject_kinds.readable & subject_kinds.actionable
    scoped = Q(subject_kind__in=kinds) & surface_q(surface)
    waiting = (
        WarehouseSuggestion.objects.for_team(team_id)
        .filter(status=WarehouseSuggestionStatus.PROPOSED, surfaced_at__isnull=True)
        .filter(scoped)
    )
    return scoped & subject_access(team_id, user_access_control, waiting, actionable_kinds=kinds).editable_q()


def can_take(team: "Team", user: "User", suggestion: WarehouseSuggestion) -> bool:
    """Whether `user` has access to the project and every edit access accepting `suggestion` needs."""
    if not team.all_users_with_access().filter(id=user.id).exists():
        return False
    return suggestion.id in _editable_suggestion_ids(team.pk, UserAccessControl(user, team), [suggestion])


def _editable_suggestion_ids(
    team_id: int, user_access_control: UserAccessControl, suggestions: Sequence[WarehouseSuggestion]
) -> frozenset[UUID]:
    catalog_editor = any(
        suggestion.kind in CATALOG_KINDS for suggestion in suggestions
    ) and user_access_control.check_access_level_for_resource("data_catalog", required_level=EDITOR_LEVEL)
    subject_ids: defaultdict[WarehouseSuggestionSubjectKind, set[UUID]] = defaultdict(set)
    for suggestion in suggestions:
        subject_ids[WarehouseSuggestionSubjectKind(suggestion.subject_kind)].add(suggestion.subject_id)
    editable = {
        subject_kind: ALLOWED_SUBJECT_IDS[subject_kind](
            team_id, user_access_control, required_level=EDITOR_LEVEL, ids=ids
        )
        for subject_kind, ids in subject_ids.items()
    }
    return frozenset(
        suggestion.id
        for suggestion in suggestions
        if suggestion.subject_id in editable[WarehouseSuggestionSubjectKind(suggestion.subject_kind)]
        and (catalog_editor or suggestion.kind not in CATALOG_KINDS)
    )


@frozen
class SubjectAccess:
    readable: Mapping[WarehouseSuggestionSubjectKind, frozenset[UUID]]
    editable: Mapping[WarehouseSuggestionSubjectKind, frozenset[UUID]]

    def readable_q(self) -> Q:
        return _subjects_q(self.readable)

    def editable_q(self) -> Q:
        return _subjects_q(self.editable)

    def decided_or_editable_q(self) -> Q:
        return ~Q(status=WarehouseSuggestionStatus.PROPOSED) | self.editable_q()

    def can_act_on(self, suggestion: WarehouseSuggestion) -> bool:
        return suggestion.subject_id in self.editable.get(
            WarehouseSuggestionSubjectKind(suggestion.subject_kind), frozenset()
        )


def _subjects_q(subject_ids_by_kind: Mapping[WarehouseSuggestionSubjectKind, frozenset[UUID]]) -> Q:
    subjects = Q(pk__in=[])
    for subject_kind, subject_ids in subject_ids_by_kind.items():
        subjects |= Q(subject_kind=subject_kind, subject_id__in=subject_ids)
    return subjects


def shown_suggestions(
    team_id: int,
    *,
    subject_kinds: SubjectKinds,
    status: WarehouseSuggestionStatus | None = None,
    subject_ids: Collection[UUID] | None = None,
) -> QuerySet[WarehouseSuggestion]:
    suggestions = (
        WarehouseSuggestion.objects.for_team(team_id)
        .filter(subject_kind__in=subject_kinds.readable)
        .exclude(status=WarehouseSuggestionStatus.PROPOSED, surfaced_at__isnull=True)
    )
    if status is not None:
        suggestions = suggestions.filter(status=status)
    if subject_ids is not None:
        suggestions = suggestions.filter(subject_id__in=subject_ids)
    return suggestions


def visible_suggestions(
    team_id: int,
    user_access_control: "UserAccessControl",
    *,
    suggestion_id: UUID | None = None,
    kind: WarehouseSuggestionKind | None = None,
    status: WarehouseSuggestionStatus | None = None,
    subject_id: UUID | None = None,
    subject_ids: Collection[UUID] | None = None,
    assignee_id: int | None = None,
    surface: WarehouseSuggestionSurface | None = None,
    subject_kinds: SubjectKinds,
) -> tuple[QuerySet[WarehouseSuggestion], SubjectAccess]:
    suggestions = shown_suggestions(team_id, subject_kinds=subject_kinds, status=status, subject_ids=subject_ids)
    if surface is not None:
        suggestions = suggestions.filter(surface_q(surface))
    if suggestion_id is not None:
        suggestions = suggestions.filter(id=suggestion_id)
    if kind is not None:
        suggestions = suggestions.filter(kind=kind)
    if subject_id is not None:
        suggestions = suggestions.filter(subject_id=subject_id)
    if assignee_id is not None:
        suggestions = suggestions.filter(assignee_id=assignee_id)
    access = subject_access(team_id, user_access_control, suggestions, actionable_kinds=subject_kinds.actionable)
    visible = (
        suggestions.filter(access.readable_q())
        .select_related("reviewed_by", "assignee")
        .annotate(kind_position=_kind_position(RULES.lifecycle.kind_order))
        .order_by("kind_position", "-score", "id")
    )
    return visible, access


@frozen
class OpenCounts:
    assigned_to_viewer: int
    unassigned: int


NO_OPEN_SUGGESTIONS = OpenCounts(assigned_to_viewer=0, unassigned=0)


def actionable_open_counts(
    team: "Team",
    user: "User",
    kinds: frozenset[WarehouseSuggestionKind],
    subject_kinds: frozenset[WarehouseSuggestionSubjectKind],
    *,
    excluded_surface: WarehouseSuggestionSurface | None = None,
) -> OpenCounts:
    """Counts the open suggestions `user` can act on: assigned to `user`, and with no assignee who can take them."""
    if not is_warehouse_suggestions_enabled(team):
        return NO_OPEN_SUGGESTIONS
    suggestions = _actionable_open(
        team, user, kinds, subject_kinds, excluded_surface, select=lambda rows: rows.only(*_ACTIONABLE_FIELDS)
    )
    return OpenCounts(
        assigned_to_viewer=sum(1 for suggestion in suggestions if suggestion.assignee_id == user.pk),
        unassigned=sum(1 for suggestion in suggestions if suggestion.assignee_id != user.pk),
    )


def actionable_open_suggestions(team: "Team", user: "User") -> list[WarehouseSuggestion]:
    """Every open suggestion `user` can act on, oldest surfaced first, each marked `on_models_surface`. Callers check the flag."""
    return _actionable_open(
        team,
        user,
        frozenset(WarehouseSuggestionKind),
        frozenset(WarehouseSuggestionSubjectKind),
        None,
        select=lambda rows: (
            rows.only(*_ACTIONABLE_FIELDS, "surfaced_at", "payload")
            .annotate(
                **{
                    ON_MODELS_SURFACE: ExpressionWrapper(
                        surface_q(WarehouseSuggestionSurface.MODELS), output_field=BooleanField()
                    )
                }
            )
            .order_by("surfaced_at", "id")
        ),
    )


def is_on_models_surface(suggestion: WarehouseSuggestion) -> bool:
    """For a suggestion from `actionable_open_suggestions`, whether Models is where it is reviewed."""
    return bool(getattr(suggestion, ON_MODELS_SURFACE))


_ACTIONABLE_FIELDS = ("id", "kind", "subject_kind", "subject_id", "assignee")
ON_MODELS_SURFACE = "on_models_surface"


def _actionable_open(
    team: "Team",
    user: "User",
    kinds: frozenset[WarehouseSuggestionKind],
    subject_kinds: frozenset[WarehouseSuggestionSubjectKind],
    excluded_surface: WarehouseSuggestionSurface | None,
    *,
    select: Callable[[QuerySet[WarehouseSuggestion]], QuerySet[WarehouseSuggestion]],
) -> list[WarehouseSuggestion]:
    visible, access = visible_suggestions(
        team.pk,
        UserAccessControl(user, team),
        status=WarehouseSuggestionStatus.PROPOSED,
        subject_kinds=SubjectKinds(readable=subject_kinds, actionable=subject_kinds),
    )
    actionable = visible.filter(access.editable_q(), kind__in=kinds)
    if excluded_surface is not None:
        actionable = actionable.exclude(surface_q(excluded_surface))
    suggestions = list(select(actionable.select_related(None).order_by()))
    taken_ids = _taken_by_other_assignees(
        team, [suggestion for suggestion in suggestions if suggestion.assignee_id not in (None, user.pk)]
    )
    return [suggestion for suggestion in suggestions if suggestion.id not in taken_ids]


def _taken_by_other_assignees(team: "Team", suggestions: Sequence[WarehouseSuggestion]) -> frozenset[UUID]:
    by_assignee: defaultdict[int, list[WarehouseSuggestion]] = defaultdict(list)
    for suggestion in suggestions:
        if suggestion.assignee_id is not None:
            by_assignee[suggestion.assignee_id].append(suggestion)
    if not by_assignee:
        return frozenset()
    assignee_uuids = [str(uuid) for uuid in User.objects.filter(id__in=by_assignee).values_list("uuid", flat=True)]
    member_ids = team.all_users_with_access(user_uuids=assignee_uuids).values_list("id", flat=True)
    return frozenset(
        suggestion_id
        for assignee_id, user_access_control in UserAccessControl.for_user_ids(user_ids=member_ids, team=team).items()
        for suggestion_id in _editable_suggestion_ids(team.pk, user_access_control, by_assignee[assignee_id])
    )


def subject_access(
    team_id: int,
    user_access_control: "UserAccessControl",
    suggestions: QuerySet[WarehouseSuggestion],
    *,
    actionable_kinds: Collection[WarehouseSuggestionSubjectKind],
) -> SubjectAccess:
    subject_ids: defaultdict[WarehouseSuggestionSubjectKind, set[UUID]] = defaultdict(set)
    for subject_kind, subject_id in suggestions.order_by().values_list("subject_kind", "subject_id").distinct():
        subject_ids[WarehouseSuggestionSubjectKind(subject_kind)].add(subject_id)
    table_ids = subject_ids[WarehouseSuggestionSubjectKind.TABLE]
    table_ids.difference_update(backing_table_ids_by_saved_query(team_id, table_ids=table_ids))
    readable = _allowed(team_id, user_access_control, "viewer", subject_ids)
    actionable = {subject_kind: ids for subject_kind, ids in readable.items() if subject_kind in actionable_kinds}
    editable = _allowed(team_id, user_access_control, "editor", actionable)
    return SubjectAccess(readable=readable, editable=editable)


def _allowed(
    team_id: int,
    user_access_control: "UserAccessControl",
    required_level: "AccessControlLevel",
    subject_ids: Mapping[WarehouseSuggestionSubjectKind, Collection[UUID]],
) -> dict[WarehouseSuggestionSubjectKind, frozenset[UUID]]:
    return {
        subject_kind: allowed_ids(
            team_id, user_access_control, required_level=required_level, ids=subject_ids.get(subject_kind, ())
        )
        for subject_kind, allowed_ids in ALLOWED_SUBJECT_IDS.items()
    }


def readable_table_ids(
    team_id: int, user_access_control: "UserAccessControl", table_ids: Collection[UUID]
) -> frozenset[UUID]:
    return ALLOWED_SUBJECT_IDS[WarehouseSuggestionSubjectKind.TABLE](team_id, user_access_control, ids=table_ids)


def _kind_position(kind_order: Sequence[WarehouseSuggestionKind]) -> Case:
    return Case(
        *(When(kind=kind, then=Value(position)) for position, kind in enumerate(kind_order)),
        default=Value(len(kind_order)),
        output_field=IntegerField(),
    )
