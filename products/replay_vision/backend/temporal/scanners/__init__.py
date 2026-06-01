"""Concrete scanner implementations + factory keyed off `ReplayScanner.scanner_type`."""

from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError
from temporalio.exceptions import ApplicationError

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.temporal.scanners.base import BaseScanner, BaseScannerOutput
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput, ClassifierScanner
from products.replay_vision.backend.temporal.scanners.indexer import IndexerLlmResponse, IndexerOutput, IndexerScanner
from products.replay_vision.backend.temporal.scanners.monitor import MonitorLlmResponse, MonitorOutput, MonitorScanner
from products.replay_vision.backend.temporal.scanners.scorer import ScorerOutput, ScorerScanner, ScoreScale
from products.replay_vision.backend.temporal.scanners.summarizer import (
    SummarizerLlmResponse,
    SummarizerOutput,
    SummarizerScanner,
)
from products.replay_vision.backend.temporal.types import AnyScannerOutput, ScannerSnapshot

AnyScanner = Annotated[
    ClassifierScanner | IndexerScanner | MonitorScanner | ScorerScanner | SummarizerScanner,
    Field(discriminator="scanner_type"),
]
_SCANNER_ADAPTER: TypeAdapter[AnyScanner] = TypeAdapter(AnyScanner)


def validate_scanner_config(
    *, scanner_config: Any, scanner_type: ScannerType, emits_signals: bool = False
) -> AnyScanner:
    """Validate `scanner_config` against the per-`scanner_type` Pydantic schema; raises `ValueError` or `pydantic.ValidationError`."""
    if not isinstance(scanner_config, dict):
        raise ValueError(f"scanner_config must be a JSON object, got {type(scanner_config).__name__}")
    # Spread `scanner_config` first so the trusted top-level columns override anything that leaked into the JSON.
    return _SCANNER_ADAPTER.validate_python(
        {**scanner_config, "scanner_type": scanner_type, "emits_signals": emits_signals}
    )


def _build_scanner(*, scanner_config: Any, scanner_type: ScannerType, emits_signals: bool, source: str) -> AnyScanner:
    try:
        return validate_scanner_config(
            scanner_config=scanner_config, scanner_type=scanner_type, emits_signals=emits_signals
        )
    except (ValueError, ValidationError) as exc:
        raise ApplicationError(f"{source}.scanner_config is invalid: {exc}", non_retryable=True) from exc


def scanner_from_db(replay_scanner: ReplayScanner) -> AnyScanner:
    """Build a concrete `BaseScanner` from the live `ReplayScanner` row."""
    return _build_scanner(
        scanner_config=replay_scanner.scanner_config,
        scanner_type=ScannerType(replay_scanner.scanner_type),
        emits_signals=replay_scanner.emits_signals,
        source="ReplayScanner",
    )


def scanner_from_snapshot(snapshot: ScannerSnapshot) -> AnyScanner:
    """Build a concrete `BaseScanner` from a `ScannerSnapshot` blob."""
    return _build_scanner(
        scanner_config=snapshot.scanner_config,
        scanner_type=snapshot.scanner_type,
        emits_signals=snapshot.emits_signals,
        source="ScannerSnapshot",
    )


__all__ = [
    "AnyScanner",
    "AnyScannerOutput",
    "BaseScanner",
    "BaseScannerOutput",
    "ClassifierScanner",
    "ClassifierOutput",
    "IndexerScanner",
    "IndexerLlmResponse",
    "IndexerOutput",
    "MonitorScanner",
    "MonitorLlmResponse",
    "MonitorOutput",
    "ScoreScale",
    "ScorerScanner",
    "ScorerOutput",
    "SummarizerScanner",
    "SummarizerLlmResponse",
    "SummarizerOutput",
    "scanner_from_db",
    "scanner_from_snapshot",
    "validate_scanner_config",
]
