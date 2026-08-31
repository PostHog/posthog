import re
from typing import TypeGuard

from products.wizard.backend.facade.config import (
    LATEST_WIZARD_VERSION,
    WIZARD_ERROR_CODE_MAX_LENGTH,
    WIZARD_ERROR_CODE_PATTERN,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment

_EXACT_WIZARD_VERSION_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_PROGRAM_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WIZARD_ERROR_CODE_PATTERN = re.compile(WIZARD_ERROR_CODE_PATTERN)


def validate_nonempty_string(value: object, *, error: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise ValueError(error)
    return value


def validate_program_id(value: object) -> str:
    if not isinstance(value, str) or _PROGRAM_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("Invalid Wizard program")
    return value


def validate_pinned_wizard_version(value: object) -> str:
    if not isinstance(value, str) or _EXACT_WIZARD_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("Invalid Wizard program")

    return value


def validate_wizard_version(value: object) -> str:
    if value == LATEST_WIZARD_VERSION:
        return LATEST_WIZARD_VERSION
    return validate_pinned_wizard_version(value)


def is_executable_wizard_version(value: object) -> bool:
    try:
        validate_wizard_version(value)
    except ValueError:
        return False
    return True


def is_wizard_error_code(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) <= WIZARD_ERROR_CODE_MAX_LENGTH
        and _WIZARD_ERROR_CODE_PATTERN.fullmatch(value) is not None
    )


def validate_program_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("Invalid Wizard program")
    values = tuple(validate_program_id(item) for item in value)
    if len(values) != len(set(values)):
        raise ValueError("Invalid Wizard program")
    return values


def validate_program_environments(value: object) -> tuple[WizardRunEnvironment, ...]:
    if not isinstance(value, list):
        raise ValueError("Invalid Wizard program")
    try:
        environments = tuple(WizardRunEnvironment(item) for item in value)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid Wizard program") from error
    if not environments or len(environments) != len(set(environments)):
        raise ValueError("Invalid Wizard program")
    return environments


def validate_workspace_metadata_value(metadata: object, key: str) -> str:
    if not isinstance(metadata, dict):
        raise ValueError("Wizard workspace metadata must be an object")
    value = metadata.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Wizard workspace metadata field {key!r} must be a string")
    return value
