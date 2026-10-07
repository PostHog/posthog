from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_catalog.backend.facade.api import certifications_for_team
from products.data_modeling.backend.facade.api import backing_table_ids_by_saved_query, saved_query_definitions
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition
from products.warehouse_sources.backend.facade.api import all_queryable_table_names, direct_access_table_ids

from ..facade.enums import WarehouseSuggestionSubjectKind
from .reads import Subject

if TYPE_CHECKING:
    from posthog.models.team import Team


@frozen
class TeamInventory:
    saved_queries: Mapping[UUID, SavedQueryDefinition]
    table_names: Mapping[UUID, str]
    certified: frozenset[Subject]
    direct_table_ids: frozenset[UUID]

    def name_of(self, subject: Subject) -> str | None:
        if subject.kind == WarehouseSuggestionSubjectKind.SAVED_QUERY:
            saved_query = self.saved_queries.get(subject.id)
            return saved_query.name if saved_query else None
        return self.table_names.get(subject.id)


def load_inventory(team: "Team") -> TeamInventory:
    table_names = all_queryable_table_names(team.pk)
    backing_table_ids = backing_table_ids_by_saved_query(team.pk, table_ids=table_names.keys())
    return TeamInventory(
        saved_queries={saved_query.id: saved_query for saved_query in saved_query_definitions(team.pk)},
        table_names={table_id: name for table_id, name in table_names.items() if table_id not in backing_table_ids},
        certified=frozenset(_certified_subjects(team)),
        direct_table_ids=frozenset(direct_access_table_ids(team.pk)),
    )


def _certified_subjects(team: "Team") -> list[Subject]:
    subjects = []
    for saved_query_id, table_id in certifications_for_team(team).values_list("saved_query_id", "table_id"):
        if saved_query_id is not None:
            subjects.append(Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query_id))
        if table_id is not None:
            subjects.append(Subject(kind=WarehouseSuggestionSubjectKind.TABLE, id=table_id))
    return subjects
