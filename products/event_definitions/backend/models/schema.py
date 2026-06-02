from django.db import models
from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.utils import timezone

from posthog.models.signals import mutable_receiver
from posthog.models.utils import UUIDTModel

from .event_definition import EventDefinition


class SchemaPropertyType(models.TextChoices):
    """Property types supported in schema definitions (includes Object for TypeScript generation)"""

    Datetime = "DateTime", "DateTime"
    String = "String", "String"
    Numeric = "Numeric", "Numeric"
    Boolean = "Boolean", "Boolean"
    Object = "Object", "Object"


class SchemaPropertyGroup(UUIDTModel):
    """
    A reusable group of properties that defines a schema.
    Can be attached to multiple events via EventSchema.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="schema_property_groups",
        related_query_name="schema_property_group",
    )
    project = models.ForeignKey("posthog.Project", on_delete=models.CASCADE, null=True)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_schema_property_groups",
    )

    class Meta:
        db_table = "posthog_schemapropertygroup"
        indexes = [
            models.Index(fields=["team", "name"], name="schema_pg_team_name_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_schema_property_group_team_name",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"


class SchemaPropertyGroupProperty(UUIDTModel):
    """
    Individual property within a property group.
    Defines the expected name, type, and whether it's required.
    """

    property_group = models.ForeignKey(
        SchemaPropertyGroup,
        on_delete=models.CASCADE,
        related_name="properties",
        related_query_name="property",
    )
    name = models.CharField(max_length=400)
    property_type = models.CharField(max_length=50, choices=SchemaPropertyType)
    is_required = models.BooleanField(default=False)
    is_optional_in_types = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_schemapropertygroupproperty"
        indexes = [
            models.Index(
                fields=["property_group", "name"],
                name="schema_pgp_group_name_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["property_group", "name"],
                name="unique_property_group_property_name",
            ),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        required_str = " (required)" if self.is_required else ""
        return f"{self.name} ({self.property_type}){required_str} / {self.property_group.name}"


class EventSchema(UUIDTModel):
    """
    Associates a property group with an event definition.
    Defines which property groups an event should have.
    """

    event_definition = models.ForeignKey(
        EventDefinition,
        on_delete=models.CASCADE,
        related_name="schemas",
        related_query_name="schema",
    )
    property_group = models.ForeignKey(
        SchemaPropertyGroup,
        on_delete=models.CASCADE,
        related_name="event_schemas",
        related_query_name="event_schema",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_eventschema"
        constraints = [
            models.UniqueConstraint(
                fields=["event_definition", "property_group"],
                name="unique_event_schema",
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_definition.name} → {self.property_group.name}"


# Signal handlers to auto-increment EventDefinition.schema_version when the schema structure changes.
# NOTE: These use @mutable_receiver, so callers using mute_selected_signals() will skip version bumps.
# If bulk-deleting schemas, ensure schema_version is bumped manually afterward.


@mutable_receiver([post_save, post_delete], sender=EventSchema)
def bump_version_on_event_schema_change(sender, instance: EventSchema, **kwargs):
    EventDefinition.objects.filter(pk=instance.event_definition_id).update(schema_version=F("schema_version") + 1)


@mutable_receiver([post_save, post_delete], sender=SchemaPropertyGroupProperty)
def bump_version_on_property_change(sender, instance: SchemaPropertyGroupProperty, **kwargs):
    EventDefinition.objects.filter(
        pk__in=EventSchema.objects.filter(property_group_id=instance.property_group_id).values("event_definition_id")
    ).update(schema_version=F("schema_version") + 1)
