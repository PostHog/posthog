"""Exported enums for event_definitions.

No Django imports, so the HogQL engine can import this module without booting Django.
"""

from posthog.enums import LabeledIntEnum, LabeledStrEnum


class PropertyDefinitionType(LabeledIntEnum):
    """Which kind of entity a property definition describes. `PropertyDefinition.Type` is this class."""

    EVENT = 1, "event"
    PERSON = 2, "person"
    GROUP = 3, "group"
    SESSION = 4, "session"


class PropertyType(LabeledStrEnum):
    """The value type of a property.

    The model keeps its own `models.TextChoices` copy in `backend/property_type.py`, because the frozen
    migration `posthog/migrations/0889_add_schema_models.py` passes that class to `choices=`, which only a
    Django choices class satisfies. `backend/tests/test_facade.py` keeps the two in step.
    """

    Datetime = "DateTime", "DateTime"
    String = "String", "String"
    Numeric = "Numeric", "Numeric"
    Boolean = "Boolean", "Boolean"
    Duration = "Duration", "Duration"
