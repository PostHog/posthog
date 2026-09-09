"""
Cross-product contracts for product_analytics.

Stable, framework-free frozen dataclasses that define what this product hands to the rest of the
codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same syntax, same
``is_dataclass()`` compatibility, but with runtime validation on construction, so a mapper that
loses a field surfaces at the facade boundary instead of further down the caller's stack.

``Insight``, ``InsightVariable`` and the QueryRunner wiring still cross as classes
(``facade.models``, ``facade.queries``); as they convert, their contracts land here too.
"""

from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class InsightVariableDefinition:
    """A saved query variable, as callers outside product analytics read it.

    ``type`` carries an ``InsightVariableType`` value; the field stays a plain ``str`` because
    that enum is a Django ``TextChoices`` and contracts hold no Django imports. Comparing it to
    ``InsightVariableType.LIST`` works either way.
    """

    id: UUID
    name: str
    code_name: str | None
    type: str
    default_value: Any = None
    is_multi: bool = False
