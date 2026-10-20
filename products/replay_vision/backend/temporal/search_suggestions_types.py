"""Search-suggestion-refresher-only types, kept out of `types.py` so the workflow sandbox loads only these."""

from uuid import UUID

from pydantic import BaseModel


class RefreshScannerSuggestionsInputs(BaseModel, frozen=True):
    team_id: int
    # None refreshes the team's cross-scanner phrases instead of one scanner's.
    scanner_id: UUID | None = None

    @property
    def key(self) -> str:
        return f"scanner:{self.scanner_id}" if self.scanner_id else f"team:{self.team_id}"


class RefreshSearchSuggestionsInputs(BaseModel, frozen=True):
    pass


class RefreshSearchSuggestionsResult(BaseModel, frozen=True):
    refreshed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
