from products.replay_vision.backend.proposers.base import ConfigChange, ConfigProposer
from products.replay_vision.backend.proposers.classifier import ClassifierProposer
from products.replay_vision.backend.proposers.monitor import MonitorProposer
from products.replay_vision.backend.proposers.scorer import ScorerProposer
from products.replay_vision.backend.proposers.summarizer import SummarizerProposer

_PROPOSERS: dict[str, ConfigProposer] = {
    MonitorProposer.scanner_type: MonitorProposer(),
    ClassifierProposer.scanner_type: ClassifierProposer(),
    ScorerProposer.scanner_type: ScorerProposer(),
    SummarizerProposer.scanner_type: SummarizerProposer(),
}


def get_proposer(scanner_type: str) -> ConfigProposer:
    return _PROPOSERS[scanner_type]


__all__ = ["ConfigChange", "ConfigProposer", "get_proposer"]
