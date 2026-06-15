from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import QuerySet
from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.reminders.backend.constants import MAX_ACTIVE_REMINDERS_PER_USER, RESOURCE_MODELS, RESOURCE_TYPES
from products.reminders.backend.models import Reminder
from products.reminders.backend.scheduling import compute_next_fire_at, exceeds_daily_frequency_cap, resolve_timezone


class ReminderSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Reminder
        fields = [
            "id",
            "title",
            "message",
            "resource_type",
            "resource_id",
            "scheduled_at",
            "recurrence_interval",
            "cron_expression",
            "timezone",
            "end_date",
            "next_fire_at",
            "last_fired_at",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "next_fire_at",
            "last_fired_at",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "title": {"help_text": "Short text shown as the notification title when the reminder fires."},
            "message": {"help_text": "Optional longer body for the notification."},
            "resource_type": {
                "help_text": f"Optional PostHog resource this reminder is about. One of: {', '.join(RESOURCE_TYPES)}.",
            },
            "resource_id": {"help_text": "ID of the referenced resource; must exist in this project."},
            "scheduled_at": {"help_text": "For a one-off reminder: when it should fire (ISO 8601, future)."},
            "recurrence_interval": {
                "help_text": "For a recurring reminder: daily, weekly, monthly, or yearly.",
            },
            "cron_expression": {
                "help_text": (
                    "For a recurring reminder: a 5-field cron expression (e.g. '0 9 * * 1' = Mondays 9am). "
                    "May fire at most 4 times per day. Mutually exclusive with recurrence_interval."
                ),
            },
            "timezone": {
                "help_text": (
                    "IANA timezone the schedule resolves in (e.g. 'America/New_York'). "
                    "Defaults to the project timezone."
                ),
            },
            "end_date": {
                "help_text": "Optional: recurring reminders stop (status=completed) after this time.",
            },
        }

    def _get_team(self) -> Any:
        return self.context["get_team"]()

    def validate_timezone(self, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError(f"Unknown timezone: {value}")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = self._get_team()
        instance = self.instance

        scheduled_at = attrs.get("scheduled_at", getattr(instance, "scheduled_at", None))
        interval = attrs.get("recurrence_interval", getattr(instance, "recurrence_interval", None))
        cron = attrs.get("cron_expression", getattr(instance, "cron_expression", None))

        if sum([bool(scheduled_at), bool(interval), bool(cron)]) != 1:
            raise ValidationError("Provide exactly one of scheduled_at, recurrence_interval, or cron_expression.")

        if scheduled_at and scheduled_at <= timezone.now():
            raise ValidationError("scheduled_at must be in the future.")

        if cron and exceeds_daily_frequency_cap(cron):
            raise ValidationError("Schedule fires too often; a reminder may fire at most 4 times per day.")

        resource_type = attrs.get("resource_type", getattr(instance, "resource_type", None))
        resource_id = attrs.get("resource_id", getattr(instance, "resource_id", None))
        if resource_type or resource_id:
            if not (resource_type and resource_id):
                raise ValidationError("resource_type and resource_id must be provided together.")
            if resource_type not in RESOURCE_MODELS:
                raise ValidationError(f"Unknown resource_type: {resource_type}")
            model, lookup_field, _ = RESOURCE_MODELS[resource_type]
            if not model._default_manager.filter(team=team, **{lookup_field: resource_id}).exists():
                raise ValidationError(f"No {resource_type} with id {resource_id} in this project.")

        if instance is None or getattr(instance, "status", None) == Reminder.Status.ACTIVE:
            request = self.context["request"]
            active = Reminder.objects.filter(
                team=team, created_by=request.user, status=Reminder.Status.ACTIVE, deleted=False
            )
            if instance is not None:
                active = active.exclude(id=instance.id)
            if active.count() >= MAX_ACTIVE_REMINDERS_PER_USER:
                raise ValidationError(
                    f"You already have {MAX_ACTIVE_REMINDERS_PER_USER} active reminders in this project."
                )

        return attrs

    def _initial_next_fire_at(self, validated: dict[str, Any], team: Any) -> datetime:
        if validated.get("scheduled_at"):
            return validated["scheduled_at"]
        tz = resolve_timezone(validated.get("timezone") or team.timezone)
        return compute_next_fire_at(
            timezone.now(),
            interval=validated.get("recurrence_interval"),
            cron_expression=validated.get("cron_expression"),
            tz=tz,
        )

    def create(self, validated_data: dict[str, Any]) -> Reminder:
        team = self._get_team()
        request = self.context["request"]
        validated_data["team"] = team
        validated_data["created_by"] = request.user
        if not validated_data.get("timezone"):
            validated_data["timezone"] = team.timezone
        validated_data["next_fire_at"] = self._initial_next_fire_at(validated_data, team)
        return super().create(validated_data)

    def update(self, instance: Reminder, validated_data: dict[str, Any]) -> Reminder:
        team = self._get_team()
        schedule_changed = any(
            k in validated_data for k in ("scheduled_at", "recurrence_interval", "cron_expression", "timezone")
        )
        reminder = super().update(instance, validated_data)
        if schedule_changed and reminder.status == Reminder.Status.ACTIVE:
            merged = {
                "scheduled_at": reminder.scheduled_at,
                "recurrence_interval": reminder.recurrence_interval,
                "cron_expression": reminder.cron_expression,
                "timezone": reminder.timezone,
            }
            reminder.next_fire_at = self._initial_next_fire_at(merged, team)
            reminder.save(update_fields=["next_fire_at"])
        return reminder


class ReminderViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "reminder"
    serializer_class = ReminderSerializer
    queryset = Reminder.objects.unscoped().select_related("created_by", "team").order_by("-created_at")

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(created_by=self.request.user, deleted=False)

    def perform_destroy(self, instance: Reminder) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted"])
