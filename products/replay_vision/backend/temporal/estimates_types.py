"""Estimate-refresher-only Temporal types — split from `types.py` to avoid a circular import."""

from uuid import UUID

from pydantic import BaseModel


class RefreshScannerEstimateInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int


class RefreshScannerEstimatesInputs(BaseModel, frozen=True):
    pass


class RefreshScannerEstimatesResult(BaseModel, frozen=True):
    refreshed: list[UUID] = []
    failed: list[UUID] = []
