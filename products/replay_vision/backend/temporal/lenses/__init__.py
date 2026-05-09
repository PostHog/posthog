from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import BaseFinalOutput, BaseSegmentOutput, Lens
from products.replay_vision.backend.temporal.lenses.classifier import ClassifierLens
from products.replay_vision.backend.temporal.lenses.indexer import IndexerLens
from products.replay_vision.backend.temporal.lenses.monitor import MonitorLens
from products.replay_vision.backend.temporal.lenses.scorer import ScorerLens
from products.replay_vision.backend.temporal.lenses.summarizer import SummarizerLens

LENS_REGISTRY: dict[LensType, type[Lens]] = {
    LensType.MONITOR: MonitorLens,
    LensType.CLASSIFIER: ClassifierLens,
    LensType.SCORER: ScorerLens,
    LensType.SUMMARIZER: SummarizerLens,
    LensType.INDEXER: IndexerLens,
}


def get_lens_impl(lens_type: LensType | str) -> type[Lens]:
    return LENS_REGISTRY[LensType(lens_type)]


__all__ = [
    "LENS_REGISTRY",
    "BaseFinalOutput",
    "BaseSegmentOutput",
    "Lens",
    "get_lens_impl",
]
