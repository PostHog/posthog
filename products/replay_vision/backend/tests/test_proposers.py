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


def test_monitor_patch_and_changes() -> None:
    proposer = get_proposer("monitor")
    base = {"prompt": "old", "allow_inconclusive": False}
    llm = {"suggested_prompt": "new", "allow_inconclusive": True, "rationale": "clearer"}
    suggested = proposer.to_config_patch(llm, base)
    assert suggested == {"prompt": "new", "allow_inconclusive": True}
    changes = proposer.to_changes(base, suggested, llm)
    kinds = {(c.kind, c.field) for c in changes}
    assert ("prompt", "prompt") in kinds
    assert ("flag", "allow_inconclusive") in kinds


def test_monitor_no_flag_change_when_equal() -> None:
    proposer = get_proposer("monitor")
    base = {"prompt": "old", "allow_inconclusive": False}
    llm = {"suggested_prompt": "new", "allow_inconclusive": False, "rationale": "x"}
    suggested = proposer.to_config_patch(llm, base)
    assert all(c.field != "allow_inconclusive" for c in proposer.to_changes(base, suggested, llm))
