"""Search-suggestion-refresher-only types, kept out of `types.py` so the workflow sandbox loads only these."""

from uuid import UUID

from pydantic import BaseModel


class RefreshScannerSuggestionsInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int


class RefreshSearchSuggestionsInputs(BaseModel, frozen=True):
    pass


class RefreshSearchSuggestionsResult(BaseModel, frozen=True):
    refreshed: list[UUID] = []
    failed: list[UUID] = []
    budget_exhausted: bool = False
