from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_catalog.backend.facade.api import certifications_for_team
from products.data_catalog.backend.facade.enums import CertificationStatus
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
    certifications: Mapping[Subject, CertificationStatus]
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
        certifications=_certifications(team),
        direct_table_ids=frozenset(direct_access_table_ids(team.pk)),
    )


def _certifications(team: "Team") -> dict[Subject, CertificationStatus]:
    certifications = {}
    for saved_query_id, table_id, status in certifications_for_team(team).values_list(
        "saved_query_id", "table_id", "status"
    ):
        if saved_query_id is not None:
            certifications[Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query_id)] = (
                CertificationStatus(status)
            )
        if table_id is not None:
            certifications[Subject(kind=WarehouseSuggestionSubjectKind.TABLE, id=table_id)] = CertificationStatus(
                status
            )
    return certifications
