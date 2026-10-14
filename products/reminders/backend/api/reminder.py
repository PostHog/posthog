from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.api.shared import UserBasicSerializer
from posthog.auth import (
    IDJagAccessTokenAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
)
from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.organization_caching import get_cached_organization_membership
from posthog.permissions import (
    ActiveOrganizationPermission,
    APIScopePermission,
    MCPAccessPermission,
    VerifiedDomainEnforcementPermission,
    get_authenticator_scoped_organization_ids,
    get_authenticator_scoped_team_ids,
    get_authenticator_user_credential,
)
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.reminders.backend.constants import MAX_ACTIVE_REMINDERS_PER_USER, RESOURCE_MODELS, RESOURCE_TYPES
from products.reminders.backend.models import Reminder
from products.reminders.backend.scheduling import compute_next_fire_at, exceeds_daily_frequency_cap, resolve_timezone


def token_scope_restrictions(request: Request) -> tuple[list[str] | None, list[int] | None]:
    """APIScopePermission.check_team_and_org_permissions returns early for `scope_object = "user"`,
    because /api/users/@me/ takes no organization or project. This viewset takes both, so it applies
    the credential's restrictions itself.
    """
    authenticator = getattr(request, "successful_authenticator", None)
    return (
        get_authenticator_scoped_organization_ids(authenticator),
        get_authenticator_scoped_team_ids(authenticator),
    )


# Tenant boundaries TeamAndOrgViewSetMixin appends in get_permissions, which a view may not remove.
# MCPAccessPermission is write-only: it reads the action to decide, so including it in the read
# filter would drop a row out of the queryset before the write path could refuse it, turning a
# refusal into a 404.
READ_BOUNDARY_PERMISSIONS = (
    VerifiedDomainEnforcementPermission,
    ActiveOrganizationPermission,
)
ORGANIZATION_BOUNDARY_PERMISSIONS = (*READ_BOUNDARY_PERMISSIONS, MCPAccessPermission)


def personal_api_key_denial(request: Request, organization: Organization) -> str | None:
    """The third leg of what check_team_and_org_permissions skips for `scope_object = "user"`.
    Mirrors APIScopePermission._check_organization_personal_api_key_restrictions, which is private
    and resolves its organization from routing attributes a root viewset does not have. The
    platform check gates every method, so this one feeds the read filter as well as the writes.
    """
    credential = get_authenticator_user_credential(getattr(request, "successful_authenticator", None))
    if not isinstance(credential, PersonalAPIKey):
        return None
    if not organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS):
        return None
    membership = get_cached_organization_membership(organization.id, cast(User, request.user))
    if membership is None:
        return None
    if not organization.members_can_use_personal_api_keys and membership.level < OrganizationMembership.Level.ADMIN:
        return (
            f"Organization '{organization.name}' does not allow using personal API keys. "
            f"Contact an admin to enable personal API keys for this organization."
        )
    return None


def deny_restricted_personal_api_key(request: Request, organization: Organization) -> None:
    denial = personal_api_key_denial(request, organization)
    if denial is not None:
        raise PermissionDenied(denial)


def readable_organization_ids(view: viewsets.ModelViewSet) -> list[Any]:
    """Organizations this request may read reminders from.

    A reminder row outlives the access that created it: the writer can lose membership, and the
    organization can be deactivated, start enforcing verified domains, or stop allowing personal
    API keys. Reads run the same boundaries as writes, or a row stays readable once its access is
    gone. A refused organization drops out of the list rather than failing the whole request,
    because the caller may hold reminders in several.
    """
    user = cast(User, view.request.user)
    memberships = UserPermissions(user).organization_memberships
    organizations = Organization.objects.filter(id__in=list(memberships.keys()))
    return [
        organization.id
        for organization in organizations
        if organization_boundary_denial(view, organization, READ_BOUNDARY_PERMISSIONS) is None
    ]


def organization_boundary_denial(
    view: viewsets.ModelViewSet,
    organization: Organization,
    permission_classes: tuple[type, ...] = ORGANIZATION_BOUNDARY_PERMISSIONS,
) -> str | None:
    """The first boundary that refuses this organization, or None when all of them admit it.

    Each class either returns False or raises, depending on the class, so both are collected here.
    Which ones apply is left to the classes: ActiveOrganizationPermission exempts session callers,
    and MCPAccessPermission admits every read.
    """
    for permission_class in permission_classes:
        permission = permission_class()
        try:
            if not permission.has_object_permission(view.request, view, organization):
                return str(getattr(permission, "message", "You cannot reach this organization."))
        except PermissionDenied as denial:
            return str(denial.detail)
    return personal_api_key_denial(view.request, organization)


def enforce_organization_boundaries(view: viewsets.ModelViewSet, organization: Organization) -> None:
    """Each boundary resolves its target from routing attributes a root viewset does not have, so
    the mixin's chain would fall back to the user's current organization, which is a UI preference.
    Hand each one the organization the request actually acts on instead.
    """
    denial = organization_boundary_denial(view, organization)
    if denial is not None:
        raise PermissionDenied(denial)


class ReminderSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    # User-scoped endpoint: no single org/team is in request context for the scoped PK fields to
    # derive from, so suppress the IDOR scoping rule. __init__ narrows both querysets to the
    # caller's own reach instead.
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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not isinstance(request.user, User):
            return
        # Resolve both relations against the caller's reach, so an id outside it fails as
        # "does not exist" like an unallocated one. Judging reach after resolution instead tells
        # the caller which ids exist, which maps allocated projects across other tenants.
        permissions = UserPermissions(cast(User, request.user))
        organization_ids = list(permissions.organization_memberships.keys())
        scoped_organizations, scoped_teams = token_scope_restrictions(request)
        if scoped_organizations is not None:
            organization_ids = [id for id in organization_ids if str(id) in scoped_organizations]
        organization_field = cast(serializers.PrimaryKeyRelatedField, self.fields["organization"])
        organization_field.queryset = Organization.objects.filter(id__in=organization_ids)
        teams = Team.objects.filter(organization_id__in=organization_ids)
        if scoped_teams is not None:
            teams = teams.filter(id__in=scoped_teams)
        cast(serializers.PrimaryKeyRelatedField, self.fields["team"]).queryset = teams

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
            "deleted",
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

        request = self.context["request"]
        scoped_organizations, scoped_teams = token_scope_restrictions(request)
        if scoped_organizations is not None and str(organization.id) not in scoped_organizations:
            raise PermissionDenied(f"This credential has no access to organization ID {organization.id}.")
        if scoped_teams is not None:
            # RootTeamMixin.save stores the row under the parent project, so judge the team the
            # row lands on. A credential scoped to a child environment does not reach that parent.
            stored_team_id = (team.parent_team_id or team.id) if team is not None else None
            if stored_team_id is None or stored_team_id not in scoped_teams:
                raise PermissionDenied("This credential is restricted to specific projects.")

        view = self.context["view"]
        enforce_organization_boundaries(view, organization)
        # A PATCH may re-point `organization`. The row's current organization caps the write too,
        # or a move out of a capped organization would escape that organization's own policy.
        current_organization = getattr(self.instance, "organization", None)
        if current_organization is not None and current_organization.id != organization.id:
            enforce_organization_boundaries(view, current_organization)

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
        resource = model._default_manager.filter(team=team, **{lookup_field: resource_id}).first()
        if resource is None:
            raise ValidationError(f"No {resource_type} with id {resource_id} in this project.")

        # Membership in the project is not access to every object in it. Report an object the
        # caller cannot view as missing, so the message does not confirm that it exists.
        user = cast(User, self.context["request"].user)
        if not UserAccessControl(user=user, team=team).check_access_level_for_object(resource, "viewer"):
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
    # Root-level viewset, so TeamAndOrgViewSetMixin adds no authenticators and every accepted
    # class must be listed here. PersonalAPIKeyAuthentication returns None for a `pha_` OAuth
    # token, so without OAuthAccessTokenAuthentication an OAuth call gets a 401.
    # Session last: DRF takes the first authenticator that returns a user, so a request carrying
    # both a cookie and a bearer token must resolve as the token, or the token's reach goes unchecked.
    authentication_classes = [
        IDJagAccessTokenAuthentication,
        OAuthAccessTokenAuthentication,
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
    ]
    queryset = Reminder.objects.none()

    def get_queryset(self) -> QuerySet[Reminder]:
        queryset = (
            Reminder.objects.filter(created_by=cast(User, self.request.user), deleted=False)
            .select_related("created_by", "team", "organization")
            .order_by("-created_at", "-id")
        )
        queryset = queryset.filter(organization_id__in=readable_organization_ids(self))
        scoped_organizations, scoped_teams = token_scope_restrictions(self.request)
        if scoped_organizations is not None:
            queryset = queryset.filter(organization_id__in=scoped_organizations)
        if scoped_teams is not None:
            queryset = queryset.filter(team_id__in=scoped_teams)
        return queryset

    def perform_destroy(self, instance: Reminder) -> None:
        enforce_organization_boundaries(self, instance.organization)
        instance.deleted = True
        instance.save(update_fields=["deleted"])
