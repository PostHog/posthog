"""Typed modules for other languages, generated from a stack description with nothing stored."""

from __future__ import annotations

from typing import Any

from ..facade.contracts import GeneratedModule, StackServiceError
from ..facade.enums import StackErrorKind
from . import validation

LANGUAGES = ("python", "golang", "typescript")


def _generator(language: str) -> Any:
    # `posthog.api` loads every viewset when it is imported, this product's own among them, so the generators load
    # on first use.
    from posthog.api.event_definition_generators.golang import GolangGenerator  # noqa: PLC0415
    from posthog.api.event_definition_generators.python import PythonGenerator  # noqa: PLC0415
    from posthog.api.event_definition_generators.typescript import TypeScriptGenerator  # noqa: PLC0415

    if language == "python":
        return PythonGenerator()
    if language == "golang":
        return GolangGenerator()
    return TypeScriptGenerator()


def generate(description: dict, language: str) -> GeneratedModule:
    """The module the event definition generators write for the events a description declares."""
    from posthog.api.event_definition_generators.description import (  # noqa: PLC0415
        generate_from_description,
        schema_from_description,
        schema_hash_from_description,
    )

    validation.check_limits(description)
    validation.check_description(description, [])
    generator = _generator(language)
    try:
        schema = schema_from_description(description)
        content = generate_from_description(generator, description)
        schema_hash = schema_hash_from_description(generator, description)
    except ValueError as error:
        raise StackServiceError(StackErrorKind.INVALID, "invalid_definition", str(error)) from error
    return GeneratedModule(
        content=content,
        language=language,
        event_count=len(schema.event_definitions),
        schema_hash=schema_hash,
        generator_version=generator.generator_version(),
    )
