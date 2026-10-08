from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.api import allowed_saved_query_ids, backing_table_ids_by_saved_query
from products.warehouse_sources.backend.facade.api import allowed_table_ids

from ..facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus, WarehouseSuggestionSubjectKind
from ..models import WarehouseSuggestion
from .rules import RULES

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl


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


@frozen
class SubjectAccess:
    readable: Mapping[WarehouseSuggestionSubjectKind, frozenset[UUID]]
    editable: Mapping[WarehouseSuggestionSubjectKind, frozenset[UUID]]

    def readable_q(self) -> Q:
        readable = Q(pk__in=[])
        for subject_kind, subject_ids in self.readable.items():
            readable |= Q(subject_kind=subject_kind, subject_id__in=subject_ids)
        return readable

    def can_act_on(self, suggestion: WarehouseSuggestion) -> bool:
        return suggestion.subject_id in self.editable.get(
            WarehouseSuggestionSubjectKind(suggestion.subject_kind), frozenset()
        )


def visible_suggestions(
    team_id: int,
    user_access_control: "UserAccessControl",
    *,
    suggestion_id: UUID | None = None,
    kind: WarehouseSuggestionKind | None = None,
    status: WarehouseSuggestionStatus | None = None,
) -> tuple[QuerySet[WarehouseSuggestion], SubjectAccess]:
    suggestions = WarehouseSuggestion.objects.for_team(team_id).exclude(
        status=WarehouseSuggestionStatus.PROPOSED, surfaced_at__isnull=True
    )
    if suggestion_id is not None:
        suggestions = suggestions.filter(id=suggestion_id)
    if kind is not None:
        suggestions = suggestions.filter(kind=kind)
    if status is not None:
        suggestions = suggestions.filter(status=status)
    access = subject_access(team_id, user_access_control, suggestions)
    visible = (
        suggestions.filter(access.readable_q())
        .select_related("reviewed_by")
        .annotate(kind_position=_kind_position(RULES.lifecycle.kind_order))
        .order_by("kind_position", "-score", "id")
    )
    return visible, access


def subject_access(
    team_id: int, user_access_control: "UserAccessControl", suggestions: QuerySet[WarehouseSuggestion]
) -> SubjectAccess:
    subject_ids: defaultdict[WarehouseSuggestionSubjectKind, set[UUID]] = defaultdict(set)
    for subject_kind, subject_id in suggestions.order_by().values_list("subject_kind", "subject_id").distinct():
        subject_ids[WarehouseSuggestionSubjectKind(subject_kind)].add(subject_id)
    table_ids = subject_ids[WarehouseSuggestionSubjectKind.TABLE]
    table_ids.difference_update(backing_table_ids_by_saved_query(team_id, table_ids=table_ids))
    readable = _allowed(team_id, user_access_control, "viewer", subject_ids)
    editable = _allowed(team_id, user_access_control, "editor", readable)
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
