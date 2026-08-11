"""Frozen scanner-config snapshots.

A leaf module: `types.py` participates in an import cycle with the `scanners` package, so anything
importable without that baggage (activities loaded early in the package init, the API layer) gets
the snapshot classes from here. `types.py` re-exports them for its existing importers.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from temporalio.exceptions import ApplicationError

from products.replay_vision.backend.models.replay_scanner import ScannerType

if TYPE_CHECKING:
    from products.replay_vision.backend.models.replay_scanner import ReplayScanner


class ScannerSnapshot(BaseModel, frozen=True):
    """Frozen view of a `ReplayScanner` at observation-create time, persisted into `ReplayObservation.scanner_snapshot`."""

    name: str
    scanner_type: ScannerType
    scanner_version: int = Field(ge=1)
    # Plain strings, not live enums: retiring a ScannerModel/ScannerProvider member must not break old-row loads.
    model: str
    provider: str
    emits_signals: bool
    scanner_config: dict[str, Any]

    @classmethod
    def from_scanner(cls, scanner: "ReplayScanner") -> "ScannerSnapshot":
        """The single scanner→snapshot field mapping; every snapshot producer must build through here."""
        return cls(
            name=scanner.name,
            scanner_type=scanner.scanner_type,
            scanner_version=scanner.scanner_version,
            model=scanner.model,
            provider=scanner.provider,
            emits_signals=scanner.emits_signals,
            scanner_config=scanner.scanner_config,
        )

    @classmethod
    def load_for(cls, observation_id: UUID, raw: dict[str, Any] | None) -> "ScannerSnapshot":
        """Validate a persisted `scanner_snapshot` blob, raising a non-retryable error tagged with the observation id."""
        try:
            return cls.model_validate(raw or {})
        except ValidationError as exc:
            raise ApplicationError(
                f"ReplayObservation {observation_id} has malformed scanner_snapshot: {exc}", non_retryable=True
            ) from exc


class BackfillScannerSnapshot(ScannerSnapshot, frozen=True):
    """Full frozen scanner config persisted into `ReplayScannerBackfill.scanner_snapshot` — the observation
    snapshot fields plus the query/sampling inputs the candidate walk needs. Freezing both keeps the
    creation-time enumeration and its cost ceiling exact for the backfill's whole lifetime."""

    query: dict[str, Any]
    sampling_rate: float = Field(ge=0.0, le=1.0)
    sampling_mode: str

    @classmethod
    def from_scanner(cls, scanner: "ReplayScanner") -> "BackfillScannerSnapshot":
        return cls(
            **ScannerSnapshot.from_scanner(scanner).model_dump(),
            query=scanner.query,
            sampling_rate=scanner.sampling_rate,
            sampling_mode=scanner.sampling_mode,
        )

    @classmethod
    def load_for_backfill(cls, backfill_id: UUID, raw: dict[str, Any] | None) -> "BackfillScannerSnapshot":
        """Validate a persisted backfill `scanner_snapshot` blob, raising a non-retryable error tagged with the backfill id."""
        try:
            return cls.model_validate(raw or {})
        except ValidationError as exc:
            raise ApplicationError(
                f"ReplayScannerBackfill {backfill_id} has malformed scanner_snapshot: {exc}", non_retryable=True
            ) from exc

    def to_observation_snapshot(self) -> ScannerSnapshot:
        return ScannerSnapshot.model_validate(self.model_dump(include=set(ScannerSnapshot.model_fields)))
