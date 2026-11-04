"""The Django choices class behind `PropertyDefinition.property_type`.

Code outside the product should import `facade.enums.PropertyType`, which holds the same members
without Django. This class stays a `models.TextChoices` because the frozen migration
`posthog/migrations/0889_add_schema_models.py` passes it to `choices=` through
products.event_definitions.backend.models.property_definition, which re-exports it.
"""

from django.db import models


class PropertyType(models.TextChoices):
    Datetime = "DateTime", "DateTime"
    String = "String", "String"
    Numeric = "Numeric", "Numeric"
    Boolean = "Boolean", "Boolean"
    Duration = "Duration", "Duration"
