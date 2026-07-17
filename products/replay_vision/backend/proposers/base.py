from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from products.replay_vision.backend.models.replay_scanner import ReplayScanner

# Persisted verbatim into ReplayScannerPromptSuggestion.changes, and read by the frontend change cards.
CHANGE_KINDS = ("prompt", "tags", "scale", "length", "flag")
CHANGE_OPS = ("set", "add", "remove", "rename")


@dataclass(frozen=True)
class ConfigChange:
    field: str
    kind: str
    op: str
    before: Any
    after: Any
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "kind": self.kind,
            "op": self.op,
            "before": self.before,
            "after": self.after,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ProposalContext:
    scanner: "ReplayScanner"
    base_config: dict[str, Any]
    user_content: str
    distinct_id: str


@runtime_checkable
class ConfigProposer(Protocol):
    scanner_type: str

    def output_schema(self) -> dict[str, Any]: ...
    def system_prompt(self) -> str: ...
    def grounding(self, scanner: "ReplayScanner") -> str: ...
    def to_config_patch(self, llm_output: dict[str, Any], base_config: dict[str, Any]) -> dict[str, Any]: ...
    def to_changes(
        self, base_config: dict[str, Any], suggested_config: dict[str, Any], llm_output: dict[str, Any]
    ) -> list[ConfigChange]: ...


def set_change(field_name: str, kind: str, before: Any, after: Any, rationale: str = "") -> list[ConfigChange]:
    if before == after:
        return []
    return [ConfigChange(field=field_name, kind=kind, op="set", before=before, after=after, rationale=rationale)]
