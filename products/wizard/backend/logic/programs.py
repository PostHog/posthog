from products.wizard.backend.facade.contracts import WizardProgram
from products.wizard.backend.facade.validation import (
    validate_nonempty_string,
    validate_pinned_wizard_version,
    validate_program_environments,
    validate_program_id,
    validate_program_ids,
    validate_wizard_version,
)

_PROGRAM_FIELDS = frozenset(
    {
        "id",
        "name",
        "description",
        "wizard_version",
        "command",
        "tags",
        "required_programs",
        "supported_environments",
    }
)


def program_to_mapping(program: WizardProgram) -> dict[str, object]:
    return {
        "id": program.id,
        "name": program.name,
        "description": program.description,
        "wizard_version": program.wizard_version,
        "command": list(program.command),
        "tags": list(program.tags),
        "required_programs": list(program.required_programs),
        "supported_environments": [environment.value for environment in program.supported_environments],
    }


def program_from_mapping(value: object, *, allow_latest_version: bool = False) -> WizardProgram:
    if not isinstance(value, dict):
        raise ValueError("Invalid Wizard program")
    fields = set(value)
    if not _PROGRAM_FIELDS.issubset(fields) or (not allow_latest_version and fields != _PROGRAM_FIELDS):
        raise ValueError("Invalid Wizard program")
    return WizardProgram(
        id=validate_program_id(value["id"]),
        name=validate_nonempty_string(value["name"], error="Invalid Wizard program"),
        description=validate_nonempty_string(value["description"], error="Invalid Wizard program"),
        wizard_version=(
            validate_wizard_version(value["wizard_version"])
            if allow_latest_version
            else validate_pinned_wizard_version(value["wizard_version"])
        ),
        command=validate_program_ids(value["command"]),
        tags=validate_program_ids(value["tags"]),
        required_programs=validate_program_ids(value["required_programs"]),
        supported_environments=validate_program_environments(value["supported_environments"]),
    )
