from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from posthog.models.utils import UniqueConstraintByExpression, UUIDTModel
from posthog.utils import invalidate_default_event_info_cache

DEFAULT_EVENT_INFO_NAMES: frozenset[str] = frozenset({"$pageview", "$screen"})


class SchemaEnforcementMode(models.TextChoices):
    ALLOW = "allow", "Allow"
    REJECT = "reject", "Reject"


class EventDefinition(UUIDTModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="event_definitions",
        related_query_name="team",
    )
    project = models.ForeignKey("posthog.Project", on_delete=models.CASCADE, null=True)
    name = models.CharField(max_length=400)
    created_at = models.DateTimeField(default=timezone.now, null=True)
    last_seen_at = models.DateTimeField(default=None, null=True)

    # DEPRECATED
    # Number of times the event has been used in a query in the last 30 rolling days (computed asynchronously every other blue moon)
    query_usage_30_day = models.IntegerField(default=None, null=True)

    # DEPRECATED
    # Volume of events in the last 30 rolling days (computed asynchronously)
    volume_30_day = models.IntegerField(default=None, null=True)

    enforcement_mode = models.CharField(
        max_length=10,
        choices=SchemaEnforcementMode,
        default=SchemaEnforcementMode.ALLOW,
    )

    promoted_property = models.CharField(max_length=400, null=True, blank=True)

    class Meta:
        db_table = "posthog_eventdefinition"
        indexes = [
            # Index on project_id foreign key
            models.Index(fields=["project"], name="posthog_eve_proj_id_f93fcbb0"),
            GinIndex(
                name="index_event_definition_name",
                fields=["name"],
                opclasses=["gin_trgm_ops"],
            ),  # To speed up DB-based fuzzy searching
            models.Index(
                fields=["team_id"],
                name="posthog_eventdef_enforce_idx",
                condition=models.Q(enforcement_mode="reject"),
            ),
        ]
        constraints = [
            UniqueConstraintByExpression(
                concurrently=True,
                name="event_definition_proj_uniq",
                expression="(coalesce(project_id, team_id), name)",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"


@receiver(pre_save, sender=EventDefinition)
def _capture_event_definition_old_name(sender: type[EventDefinition], instance: EventDefinition, **kwargs) -> None:
    if instance.pk:
        try:
            instance._old_name = EventDefinition.objects.get(pk=instance.pk).name  # type: ignore[attr-defined]
        except EventDefinition.DoesNotExist:
            instance._old_name = None  # type: ignore[attr-defined]
    else:
        instance._old_name = None  # type: ignore[attr-defined]


@receiver(post_save, sender=EventDefinition)
def _invalidate_default_event_info_on_save(sender: type[EventDefinition], instance: EventDefinition, **kwargs) -> None:
    old_name: str | None = getattr(instance, "_old_name", None)
    if instance.name in DEFAULT_EVENT_INFO_NAMES or old_name in DEFAULT_EVENT_INFO_NAMES:
        invalidate_default_event_info_cache(instance.team_id)


@receiver(post_delete, sender=EventDefinition)
def _invalidate_default_event_info_on_delete(
    sender: type[EventDefinition], instance: EventDefinition, **kwargs
) -> None:
    if instance.name in DEFAULT_EVENT_INFO_NAMES:
        invalidate_default_event_info_cache(instance.team_id)
