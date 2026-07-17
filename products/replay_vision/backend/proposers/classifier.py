"""Classifier scanner config proposer. Stubbed here, fleshed out in Task 4."""

from typing import TYPE_CHECKING, Any

from products.replay_vision.backend.proposers.base import ConfigChange

if TYPE_CHECKING:
    from products.replay_vision.backend.models.replay_scanner import ReplayScanner


class ClassifierProposer:
    scanner_type = "classifier"

    def output_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    def system_prompt(self) -> str:
        raise NotImplementedError

    def grounding(self, scanner: "ReplayScanner") -> str:
        raise NotImplementedError

    def to_config_patch(self, llm_output: dict[str, Any], base_config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def to_changes(
        self, base_config: dict[str, Any], suggested_config: dict[str, Any], llm_output: dict[str, Any]
    ) -> list[ConfigChange]:
        raise NotImplementedError
