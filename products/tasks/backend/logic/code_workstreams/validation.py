from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .situations import SITUATION_IDS


@dataclass
class ValidationDiagnostic:
    severity: str
    code: str
    message: str
    situation_id: str | None = None
    action_id: str | None = None


@dataclass
class ValidationResult:
    diagnostics: list[ValidationDiagnostic]
    can_save: bool


def validate_bindings(bindings: Mapping[str, Any]) -> ValidationResult:
    diagnostics: list[ValidationDiagnostic] = []

    if not isinstance(bindings, dict):
        return ValidationResult(
            diagnostics=[
                ValidationDiagnostic(
                    severity="error",
                    code="bindings_not_object",
                    message="bindings must be an object",
                )
            ],
            can_save=False,
        )

    for sid in SITUATION_IDS:
        actions = bindings.get(sid) or []
        if not isinstance(actions, list):
            diagnostics.append(
                ValidationDiagnostic(
                    severity="error",
                    code="situation_not_list",
                    message=f"{sid} must be a list of actions",
                    situation_id=sid,
                )
            )
            continue
        seen_ids: set[str] = set()
        for action in actions:
            if not isinstance(action, dict):
                diagnostics.append(
                    ValidationDiagnostic(
                        severity="error",
                        code="action_not_object",
                        message=f"An action in {sid} must be an object",
                        situation_id=sid,
                    )
                )
                continue
            action_id = str(action.get("id", ""))
            if action_id in seen_ids:
                diagnostics.append(
                    ValidationDiagnostic(
                        severity="error",
                        code="duplicate_action_id",
                        message=f'Duplicate action id "{action_id}" in {sid}',
                        situation_id=sid,
                        action_id=action_id,
                    )
                )
                continue
            seen_ids.add(action_id)

            label = str(action.get("label", ""))
            prompt = str(action.get("prompt", ""))

            if label.strip() == "":
                diagnostics.append(
                    ValidationDiagnostic(
                        severity="error",
                        code="action_empty_label",
                        message=f"An action in {sid} has no label",
                        situation_id=sid,
                        action_id=action_id,
                    )
                )
            if prompt.strip() == "":
                diagnostics.append(
                    ValidationDiagnostic(
                        severity="error",
                        code="action_empty_prompt",
                        message=f'Action "{label}" in {sid} has an empty prompt',
                        situation_id=sid,
                        action_id=action_id,
                    )
                )

    can_save = not any(d.severity == "error" for d in diagnostics)
    return ValidationResult(diagnostics=diagnostics, can_save=can_save)
