from products.replay_vision.backend.proposers.base import ConfigChange, ConfigProposer
from products.replay_vision.backend.proposers.classifier import ClassifierProposer
from products.replay_vision.backend.proposers.monitor import MonitorProposer

_PROPOSERS: dict[str, ConfigProposer] = {
    MonitorProposer.scanner_type: MonitorProposer(),
    ClassifierProposer.scanner_type: ClassifierProposer(),
}


def get_proposer(scanner_type: str) -> ConfigProposer:
    return _PROPOSERS[scanner_type]


__all__ = ["ConfigChange", "ConfigProposer", "get_proposer"]
