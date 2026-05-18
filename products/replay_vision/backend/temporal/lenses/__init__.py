"""Concrete lens implementations + factory keyed off `ReplayLens.lens_type`."""

from typing import Annotated

from pydantic import Field, TypeAdapter, ValidationError
from temporalio.exceptions import ApplicationError

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.temporal.lenses.base import BaseLens, BaseLensOutput
from products.replay_vision.backend.temporal.lenses.classifier import ClassifierLens, ClassifierOutput
from products.replay_vision.backend.temporal.lenses.indexer import IndexerLens, IndexerOutput
from products.replay_vision.backend.temporal.lenses.monitor import MonitorLens, MonitorOutput
from products.replay_vision.backend.temporal.lenses.scorer import ScorerLens, ScorerOutput, ScoreScale
from products.replay_vision.backend.temporal.lenses.summarizer import SummarizerLens, SummarizerOutput

AnyLens = Annotated[
    ClassifierLens | IndexerLens | MonitorLens | ScorerLens | SummarizerLens,
    Field(discriminator="lens_type"),
]
_LENS_ADAPTER: TypeAdapter[AnyLens] = TypeAdapter(AnyLens)


def lens_from_db(replay_lens: ReplayLens) -> AnyLens:
    """Build the concrete `BaseLens` subclass for `replay_lens`, validating `lens_config` against its per-type schema."""
    config = replay_lens.lens_config
    if not isinstance(config, dict):
        raise ApplicationError(
            f"ReplayLens.lens_config must be a JSON object, got {type(config).__name__}",
            non_retryable=True,
        )
    # Spread `lens_config` first so the trusted `ReplayLens` columns override anything that may have leaked into the JSON blob.
    try:
        return _LENS_ADAPTER.validate_python(
            {**config, "lens_type": replay_lens.lens_type, "emits_signals": replay_lens.emits_signals}
        )
    except ValidationError as exc:
        raise ApplicationError(f"ReplayLens.lens_config is invalid: {exc}", non_retryable=True) from exc


__all__ = [
    "AnyLens",
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
]
