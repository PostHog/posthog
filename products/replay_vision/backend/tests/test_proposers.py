from typing import Any

import pytest

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.proposers import get_proposer
from products.replay_vision.backend.proposers.base import ConfigChange
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


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


def test_classifier_patch_applies_tag_ops() -> None:
    proposer = get_proposer("classifier")
    base = {"prompt": "p", "tags": ["checkout", "browse"]}
    llm = {
        "suggested_prompt": "p2",
        "tag_ops": [
            {"op": "add", "tag": "payment_failed", "rationale": "recurring"},
            {"op": "remove", "tag": "browse", "rationale": "never used"},
            {"op": "rename", "tag": "checkout", "to": "checkout_complete", "rationale": "clarity"},
        ],
        "rationale": "tighten vocab",
    }
    suggested = proposer.to_config_patch(llm, base)
    assert set(suggested["tags"]) == {"payment_failed", "checkout_complete"}
    changes = proposer.to_changes(base, suggested, llm)
    ops = {(c.op, c.field) for c in changes if c.kind == "tags"}
    assert ops == {("add", "tags"), ("remove", "tags"), ("rename", "tags")}
    assert any(c.kind == "prompt" for c in changes)


@pytest.mark.parametrize(
    "op",
    [
        {"op": "add", "tag": "checkout"},  # already in the vocabulary
        {"op": "remove", "tag": "missing"},  # never existed
        {"op": "rename", "tag": "missing", "to": "renamed"},  # nothing to rename
    ],
)
def test_classifier_patch_ignores_ops_that_dont_apply(op: dict[str, Any]) -> None:
    # An LLM tag op can reference a tag that's already gone, already present, or never existed.
    # _apply_tag_ops must leave the vocabulary untouched rather than duplicate a tag or raise.
    proposer = get_proposer("classifier")
    base = {"prompt": "p", "tags": ["checkout"]}
    llm = {"suggested_prompt": "p", "tag_ops": [op], "rationale": "r"}

    suggested = proposer.to_config_patch(llm, base)

    assert suggested["tags"] == ["checkout"]


class TestClassifierGrounding(_VisionAPITestCase):
    def test_grounding_reuses_tag_suggestions_evidence(self) -> None:
        # A sibling classifier's vocabulary is real evidence tag_suggestions._sibling_vocabularies assembles.
        # It only reaches the briefing if grounding() genuinely calls into tag_suggestions instead of a
        # stub or a from-scratch reimplementation of that evidence gathering.
        self._create_scanner(
            name="sibling",
            scanner_type=ScannerType.CLASSIFIER,
            scanner_config={"prompt": "sibling goal", "tags": ["confused_user"], "multi_label": True},
        )
        scanner = self._create_scanner(
            name="target",
            scanner_type=ScannerType.CLASSIFIER,
            scanner_config={"prompt": "categorize by intent", "tags": ["pricing"], "multi_label": True},
            created_by=self.user,
        )

        briefing = get_proposer("classifier").grounding(scanner)

        assert "categorize by intent" in briefing
        assert "pricing" in briefing
        assert "confused_user" in briefing
