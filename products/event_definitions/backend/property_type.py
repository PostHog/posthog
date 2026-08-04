"""Property-type enum the HogQL engine can import without booting Django (no settings or app registry).

`django.db.models.TextChoices` is plain enum machinery — defining a subclass touches neither
settings nor the app registry, so this module imports cleanly in a bare interpreter.
products.event_definitions.backend.models.property_definition re-exports `PropertyType` for
existing callers.
"""

from django.db import models


class PropertyType(models.TextChoices):
    Datetime = "DateTime", "DateTime"
    String = "String", "String"
    Numeric = "Numeric", "Numeric"
    Boolean = "Boolean", "Boolean"
    Duration = "Duration", "Duration"
