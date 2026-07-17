from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import Organization, Team, User
from posthog.permissions import APIScopePermission
from posthog.user_permissions import UserPermissions

from products.reminders.backend.constants import MAX_ACTIVE_REMINDERS_PER_USER, RESOURCE_MODELS, RESOURCE_TYPES
from products.reminders.backend.models import Reminder
from products.reminders.backend.scheduling import compute_next_fire_at, exceeds_daily_frequency_cap, resolve_timezone


class ReminderSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    # User-scoped endpoint: the user picks the org/team from their own memberships and
    # _validate_membership enforces access — there is no single org/team in request context
    # for the scoped PK fields to derive from, so suppress the IDOR scoping rule here.
    organization = serializers.PrimaryKeyRelatedField(  # nosemgrep: unscoped-primary-key-related-field
        queryset=Organization.objects.all(),
        help_text="ID of the organization this reminder belongs to. You must be a member of it.",
    )
    team = serializers.PrimaryKeyRelatedField(  # nosemgrep: unscoped-primary-key-related-field
        queryset=Team.objects.all(),
        required=False,
        allow_null=True,
        help_text=(
            "Optional ID of the project this reminder is scoped to. "
            "Required when targeting a specific resource. Must belong to the chosen organization."
        ),
    )

    class Meta:
        model = Reminder
        fields = [
            "id",
            "organization",
            "team",
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
                "help_text": (
                    f"Optional PostHog resource this reminder is about. One of: {', '.join(RESOURCE_TYPES)}. "
                    "Resources are project-scoped, so a team must be set when this is provided."
                ),
            },
            "resource_id": {"help_text": "ID of the referenced resource; must exist in the chosen project."},
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
                    "Defaults to the project timezone when a team is set, otherwise UTC."
                ),
            },
            "end_date": {
                "help_text": "Optional: recurring reminders stop (status=completed) after this time.",
            },
        }

    def validate_timezone(self, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError(f"Unknown timezone: {value}")
        return value

    def _validate_membership(self, organization: Organization | None, team: Team | None) -> None:
        if organization is None:
            raise ValidationError("An organization is required.")

        user = cast(User, self.context["request"].user)
        permissions = UserPermissions(user)

        if organization.id not in permissions.organization_memberships:
            raise ValidationError("You are not a member of this organization.")

        if team is not None:
            if team.organization_id != organization.id:
                raise ValidationError("The team does not belong to the chosen organization.")
            if permissions.team(team).effective_membership_level is None:
                raise ValidationError("You do not have access to this team.")

    def _validate_resource(self, attrs: dict[str, Any], team: Team | None) -> None:
        instance = self.instance
        resource_type = attrs.get("resource_type", getattr(instance, "resource_type", None))
        resource_id = attrs.get("resource_id", getattr(instance, "resource_id", None))

        if not (resource_type or resource_id):
            return

        if not (resource_type and resource_id):
            raise ValidationError("resource_type and resource_id must be provided together.")
        if team is None:
            raise ValidationError("A team must be set to attach a resource to a reminder.")
        if resource_type not in RESOURCE_MODELS:
            raise ValidationError(f"Unknown resource_type: {resource_type}")

        model, lookup_field, _ = RESOURCE_MODELS[resource_type]
        if not model._default_manager.filter(team=team, **{lookup_field: resource_id}).exists():
            raise ValidationError(f"No {resource_type} with id {resource_id} in this project.")

    def _validate_active_cap(self) -> None:
        instance = self.instance
        if instance is not None and getattr(instance, "status", None) != Reminder.Status.ACTIVE:
            return

        user = self.context["request"].user
        active = Reminder.objects.filter(created_by=user, status=Reminder.Status.ACTIVE, deleted=False)
        if instance is not None:
            active = active.exclude(id=instance.id)
        if active.count() >= MAX_ACTIVE_REMINDERS_PER_USER:
            raise ValidationError(f"You already have {MAX_ACTIVE_REMINDERS_PER_USER} active reminders.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = self.instance

        organization = attrs.get("organization", getattr(instance, "organization", None))
        team = attrs.get("team", getattr(instance, "team", None))

        scheduled_at = attrs.get("scheduled_at", getattr(instance, "scheduled_at", None))
        interval = attrs.get("recurrence_interval", getattr(instance, "recurrence_interval", None))
        cron = attrs.get("cron_expression", getattr(instance, "cron_expression", None))

        if sum([bool(scheduled_at), bool(interval), bool(cron)]) != 1:
            raise ValidationError("Provide exactly one of scheduled_at, recurrence_interval, or cron_expression.")

        # Only enforce a future time on new or still-active reminders; a fired one-off keeps its
        # past scheduled_at, and editing its title/message shouldn't be rejected over that.
        is_active = instance is None or instance.status == Reminder.Status.ACTIVE
        if scheduled_at and is_active and scheduled_at <= timezone.now():
            raise ValidationError("scheduled_at must be in the future.")

        if cron and exceeds_daily_frequency_cap(cron):
            raise ValidationError("Schedule fires too often; a reminder may fire at most 4 times per day.")

        self._validate_membership(organization, team)
        self._validate_resource(attrs, team)
        self._validate_active_cap()

        return attrs

    def _initial_next_fire_at(self, validated: dict[str, Any], tz_name: str) -> datetime:
        if validated.get("scheduled_at"):
            return validated["scheduled_at"]
        tz = resolve_timezone(validated.get("timezone") or tz_name)
        return compute_next_fire_at(
            timezone.now(),
            interval=validated.get("recurrence_interval"),
            cron_expression=validated.get("cron_expression"),
            tz=tz,
        )

    def create(self, validated_data: dict[str, Any]) -> Reminder:
        request = self.context["request"]
        team: Team | None = validated_data.get("team")
        validated_data["created_by"] = request.user

        default_tz = team.timezone if team is not None else "UTC"
        if not validated_data.get("timezone"):
            validated_data["timezone"] = default_tz
        validated_data["next_fire_at"] = self._initial_next_fire_at(validated_data, default_tz)
        return super().create(validated_data)

    def update(self, instance: Reminder, validated_data: dict[str, Any]) -> Reminder:
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
            default_tz = reminder.team.timezone if reminder.team_id else "UTC"
            reminder.next_fire_at = self._initial_next_fire_at(merged, default_tz)
            reminder.save(update_fields=["next_fire_at"])
        return reminder


@extend_schema(extensions={"x-product": "reminders"})
class ReminderViewSet(viewsets.ModelViewSet):
    scope_object = "user"
    serializer_class = ReminderSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    authentication_classes = [PersonalAPIKeyAuthentication, SessionAuthentication]
    queryset = Reminder.objects.none()

    def get_queryset(self) -> QuerySet[Reminder]:
        return (
            Reminder.objects.filter(created_by=cast(User, self.request.user), deleted=False)
            .select_related("created_by", "team", "organization")
            .order_by("-created_at")
        )

    def perform_destroy(self, instance: Reminder) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted"])
