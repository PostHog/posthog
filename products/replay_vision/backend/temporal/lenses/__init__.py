"""Concrete lens implementations + factory keyed off `ReplayLens.lens_type`."""

from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError
from temporalio.exceptions import ApplicationError

from products.replay_vision.backend.models.replay_lens import LensType, ReplayLens
from products.replay_vision.backend.temporal.lenses.base import BaseLens, BaseLensOutput
from products.replay_vision.backend.temporal.lenses.classifier import ClassifierLens, ClassifierOutput
from products.replay_vision.backend.temporal.lenses.indexer import IndexerLens, IndexerOutput
from products.replay_vision.backend.temporal.lenses.monitor import MonitorLens, MonitorOutput
from products.replay_vision.backend.temporal.lenses.scorer import ScorerLens, ScorerOutput, ScoreScale
from products.replay_vision.backend.temporal.lenses.summarizer import SummarizerLens, SummarizerOutput
from products.replay_vision.backend.temporal.types import AnyLensOutput, LensSnapshot

AnyLens = Annotated[
    ClassifierLens | IndexerLens | MonitorLens | ScorerLens | SummarizerLens,
    Field(discriminator="lens_type"),
]
_LENS_ADAPTER: TypeAdapter[AnyLens] = TypeAdapter(AnyLens)


def validate_lens_config(*, lens_config: Any, lens_type: LensType, emits_signals: bool = False) -> AnyLens:
    """Validate `lens_config` against the per-`lens_type` Pydantic schema; raises `ValueError` or `pydantic.ValidationError`."""
    if not isinstance(lens_config, dict):
        raise ValueError(f"lens_config must be a JSON object, got {type(lens_config).__name__}")
    # Spread `lens_config` first so the trusted top-level columns override anything that leaked into the JSON.
    return _LENS_ADAPTER.validate_python({**lens_config, "lens_type": lens_type, "emits_signals": emits_signals})


def _build_lens(*, lens_config: Any, lens_type: LensType, emits_signals: bool, source: str) -> AnyLens:
    try:
        return validate_lens_config(lens_config=lens_config, lens_type=lens_type, emits_signals=emits_signals)
    except (ValueError, ValidationError) as exc:
        raise ApplicationError(f"{source}.lens_config is invalid: {exc}", non_retryable=True) from exc


def lens_from_db(replay_lens: ReplayLens) -> AnyLens:
    """Build a concrete `BaseLens` from the live `ReplayLens` row."""
    return _build_lens(
        lens_config=replay_lens.lens_config,
        lens_type=LensType(replay_lens.lens_type),
        emits_signals=replay_lens.emits_signals,
        source="ReplayLens",
    )


def lens_from_snapshot(snapshot: LensSnapshot) -> AnyLens:
    """Build a concrete `BaseLens` from a `LensSnapshot` blob."""
    return _build_lens(
        lens_config=snapshot.lens_config,
        lens_type=snapshot.lens_type,
        emits_signals=snapshot.emits_signals,
        source="LensSnapshot",
    )


__all__ = [
    "AnyLens",
    "AnyLensOutput",
    "BaseLens",
    "BaseLensOutput",
    "ClassifierLens",
    "ClassifierOutput",
    "IndexerLens",
    "IndexerOutput",
    "MonitorLens",
    "MonitorOutput",
    "ScoreScale",
    "ScorerLens",
    "ScorerOutput",
    "SummarizerLens",
    "SummarizerOutput",
    "lens_from_db",
    "lens_from_snapshot",
    "validate_lens_config",
]
