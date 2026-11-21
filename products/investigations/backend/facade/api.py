from uuid import UUID

from ..logic import operations
from .contracts import InvestigationDocument, InvestigationSummary, SavedInvestigation


def list_investigations(team_id: int, search: str, offset: int, limit: int) -> tuple[list[InvestigationSummary], int]:
    return operations.list_investigations(team_id, search, offset, limit)


def get_investigation(team_id: int, id: UUID) -> SavedInvestigation:
    return operations.get_investigation(team_id, id)


def create_investigation(team_id: int, user_id: int, document: InvestigationDocument) -> SavedInvestigation:
    return operations.create_investigation(team_id, user_id, document)


def update_investigation(
    team_id: int, id: UUID, revision: int, document: InvestigationDocument | None, deleted: bool = False
) -> SavedInvestigation:
    return operations.update_investigation(team_id, id, revision, document, deleted)
