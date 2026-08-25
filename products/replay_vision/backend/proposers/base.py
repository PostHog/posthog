from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from products.replay_vision.backend.models.replay_scanner import ReplayScanner


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


def prompt_change(base_config: dict[str, Any], suggested_config: dict[str, Any], rationale: str) -> list[ConfigChange]:
    # The suggested prompt is already stripped by to_config_patch. Strip the base too so a whitespace-only
    # difference in the stored prompt is not treated as a change.
    return set_change(
        "prompt", "prompt", (base_config.get("prompt") or "").strip(), suggested_config.get("prompt", ""), rationale
    )
