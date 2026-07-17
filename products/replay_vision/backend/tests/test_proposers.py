import pytest

from products.replay_vision.backend.proposers import get_proposer
from products.replay_vision.backend.proposers.base import ConfigChange


def test_registry_returns_monitor_and_classifier() -> None:
    assert get_proposer("monitor").scanner_type == "monitor"
    assert get_proposer("classifier").scanner_type == "classifier"


def test_registry_rejects_unknown_type() -> None:
    with pytest.raises(KeyError):
        get_proposer("scorer")  # scorer proposer lands in Phase 2


def test_config_change_to_dict_roundtrip() -> None:
    change = ConfigChange(field="prompt", kind="prompt", op="set", before="a", after="b", rationale="why")
    assert change.to_dict() == {
        "field": "prompt",
        "kind": "prompt",
        "op": "set",
        "before": "a",
        "after": "b",
        "rationale": "why",
    }
