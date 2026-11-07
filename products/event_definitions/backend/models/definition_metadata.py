from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.manager import TeamScopedManager

from .event_definition import EventDefinition
from .property_definition import PropertyDefinition


class DefinitionMetadata(models.Model):
    """The fields people edit on a definition, kept out of the definition tables that ingestion writes.

    A row exists for each definition that has an ee row, which the app creates when someone opens or
    edits the definition. team_id is the definition's own team_id, so the team filter that guards a
    definition row also reaches its metadata row. For a definition first seen in a child environment
    that is the child's id, not the canonical team.
    """

    # No foreign key here has a database constraint. Creating one locks the referenced table against
    # writes, and ingestion writes the definition tables at event rate. Django still cascades and
    # sets nulls, because it collects the related rows itself.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    description = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        "posthog.User", null=True, blank=True, on_delete=models.SET_NULL, db_constraint=False, related_name="+"
    )
    verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        "posthog.User", null=True, blank=True, on_delete=models.SET_NULL, db_constraint=False, related_name="+"
    )
    hidden = models.BooleanField(null=True, blank=True, default=False)

    objects = TeamScopedManager()

    class Meta:
        abstract = True


class EventDefinitionMetadata(DefinitionMetadata):
    event_definition = models.OneToOneField(
        EventDefinition, on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="metadata"
    )
    owner = models.ForeignKey(
        "posthog.User", null=True, blank=True, on_delete=models.SET_NULL, db_constraint=False, related_name="+"
    )
    # Columns of the event definition view, like team.live_events_columns
    default_columns = ArrayField(models.TextField(), null=True, blank=True)


class PropertyDefinitionMetadata(DefinitionMetadata):
    property_definition = models.OneToOneField(
        PropertyDefinition, on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="metadata"
    )
