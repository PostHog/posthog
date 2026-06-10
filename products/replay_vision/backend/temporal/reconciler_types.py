"""Reconciler-only Temporal types — split from `types.py` to avoid a circular import."""

from uuid import UUID

from pydantic import BaseModel


class EnabledScannerEntry(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int
    fingerprint: str


class ScannerScheduleEntry(BaseModel, frozen=True):
    scanner_id: UUID
    # None for legacy schedules without a stamped fingerprint; treated as drift.
    fingerprint: str | None


class UpsertScannerScheduleActivityInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int


class DeleteScannerScheduleActivityInputs(BaseModel, frozen=True):
    scanner_id: UUID


class ReconcileScannerSchedulesInputs(BaseModel, frozen=True):
    pass


class ReconcileScannerSchedulesResult(BaseModel, frozen=True):
    upserted: list[UUID] = []
    deleted: list[UUID] = []
    failed_upsert: list[UUID] = []
    failed_delete: list[UUID] = []
