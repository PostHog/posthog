import json

from products.wizard.backend.facade.config import WIZARD_REGISTRY_VERSION
from products.wizard.backend.facade.contracts import WizardRegistry
from products.wizard.backend.logic.programs import program_from_mapping

_REGISTRY_FIELDS = frozenset({"version", "programs"})


def parse_registry_payload(value: object) -> WizardRegistry:
    decoded = _decode_payload(value)
    if not isinstance(decoded, dict) or set(decoded) != _REGISTRY_FIELDS:
        raise ValueError("Invalid Wizard registry")
    if type(decoded["version"]) is not int or decoded["version"] != WIZARD_REGISTRY_VERSION:
        raise ValueError("Invalid Wizard registry")
    if not isinstance(decoded["programs"], list):
        raise ValueError("Invalid Wizard registry")
    programs = tuple(program_from_mapping(program) for program in decoded["programs"])
    if len(programs) != len({program.id for program in programs}):
        raise ValueError("Invalid Wizard registry")
    return WizardRegistry(programs=programs)


def _decode_payload(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid Wizard registry") from error
