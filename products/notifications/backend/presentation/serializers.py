from datetime import datetime
from enum import Enum
from uuid import UUID

from django.utils.dateparse import parse_datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.notifications.backend.facade.enums import NotificationType, Priority, SourceType, TargetType

BULK_NOTIFICATION_IDS_MAX = 500
LIST_SEPARATOR = ","
CURSOR_SEPARATOR = ","


@extend_schema_field(OpenApiTypes.OBJECT)
class _NotificationMetadataField(serializers.JSONField):
    pass


class NotificationEventSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Unique ID of the notification.")
    team_id = serializers.IntegerField(
        allow_null=True, help_text="Project the notification belongs to. Null for organization-wide notifications."
    )
    notification_type = serializers.CharField(help_text="Kind of notification, such as `comment_mention`.")
    priority = serializers.CharField(help_text="`normal` or `critical`.")
    title = serializers.CharField(help_text="One-line summary shown in the notification list.")
    body = serializers.CharField(help_text="Longer description. Can be empty.")
    read = serializers.BooleanField(help_text="Whether the current user has read the notification.")
    read_at = serializers.DateTimeField(allow_null=True, help_text="When the current user read it, if they did.")
    archived = serializers.BooleanField(help_text="Whether the current user has archived the notification.")
    target_type = serializers.CharField(
        help_text="Who the notification was sent to: `user`, `role`, `team` or `organization`."
    )
    target_id = serializers.CharField(help_text="ID of the user, role, project or organization it was sent to.")
    resource_type = serializers.CharField(
        allow_null=True, help_text="Type of the object the notification is about, such as `insight`."
    )
    resource_id = serializers.CharField(help_text="ID of the object the notification is about. Can be empty.")
    source_url = serializers.CharField(help_text="Link to open for this notification. Can be empty.")
    source_type = serializers.ChoiceField(choices=[(s.value, s.name) for s in SourceType], allow_null=True)
    source_id = serializers.CharField(allow_null=True, help_text="ID of the page to open, read with `source_type`.")
    metadata = _NotificationMetadataField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional structured payload for rich client-side rendering, specific to the notification "
            "type. For `web_analytics_digest`, holds the weekly metrics (visitors, pageviews, sessions, "
            "bounce rate, session duration with week-over-week change), top pages, and top sources used "
            "to render the digest card."
        ),
    )
    created_at = serializers.DateTimeField(help_text="When the notification was created.")


def _parse_enum_list(raw: str, enum: type[Enum], field: str) -> list[str]:
    values = [value.strip() for value in raw.split(LIST_SEPARATOR) if value.strip()]
    allowed = {member.value for member in enum}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise serializers.ValidationError(f"Unknown {field}: {', '.join(unknown)}")
    return values


def _parse_timestamp(raw: str) -> datetime:
    # Django decodes "+" timezone offsets in query strings as " "; restore before parsing.
    parsed = parse_datetime(raw.replace(" ", "+"))
    if parsed is None:
        raise serializers.ValidationError(f"Invalid ISO 8601 timestamp: {raw}")
    return parsed


class NotificationFiltersQuerySerializer(serializers.Serializer):
    notification_type = serializers.CharField(
        required=False, help_text="Comma-separated notification types to include, such as `comment_mention,reminder`."
    )
    target_type = serializers.CharField(
        required=False,
        help_text="Comma-separated recipient kinds to include: `user`, `role`, `team`, `organization`.",
    )
    target_id = serializers.CharField(required=False, help_text="Only notifications sent to this recipient ID.")
    resource_type = serializers.CharField(
        required=False, help_text="Only notifications about this kind of object, such as `insight`."
    )
    resource_id = serializers.CharField(required=False, help_text="Only notifications about the object with this ID.")
    team_id = serializers.IntegerField(
        required=False,
        help_text="Only notifications from this project, plus organization-wide ones, which belong to no project.",
    )
    priority = serializers.CharField(
        required=False, help_text="Only notifications with this priority: `normal` or `critical`."
    )
    read = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="`false` returns only unread notifications, `true` only read ones. Leave out for both.",
    )
    created_after = serializers.CharField(
        required=False, help_text="ISO 8601 timestamp; only notifications created at or after this time."
    )
    created_before = serializers.CharField(
        required=False, help_text="ISO 8601 timestamp; only notifications created strictly before this time."
    )

    def validate_notification_type(self, value: str) -> list[str]:
        return _parse_enum_list(value, NotificationType, "notification_type")

    def validate_target_type(self, value: str) -> list[str]:
        return _parse_enum_list(value, TargetType, "target_type")

    def validate_priority(self, value: str) -> str:
        if value not in {priority.value for priority in Priority}:
            raise serializers.ValidationError(f"Unknown priority: {value}")
        return value

    def validate_created_after(self, value: str) -> datetime:
        return _parse_timestamp(value)

    def validate_created_before(self, value: str) -> datetime:
        return _parse_timestamp(value)


class NotificationListQuerySerializer(NotificationFiltersQuerySerializer):
    archived = serializers.BooleanField(
        required=False,
        default=False,
        help_text="When true, return only archived notifications; otherwise only non-archived ones (the default).",
    )
    before = serializers.CharField(
        required=False,
        help_text=(
            "Cursor from `next_cursor` of the previous page. Returns notifications older than that page. "
            "Read and archive changes between pages never shift it, unlike `offset`."
        ),
    )

    def validate_before(self, value: str) -> tuple[datetime, UUID]:
        created_at, separator, event_id = value.rpartition(CURSOR_SEPARATOR)
        if not separator:
            raise serializers.ValidationError("Invalid cursor")
        try:
            return _parse_timestamp(created_at), UUID(event_id)
        except ValueError:
            raise serializers.ValidationError("Invalid cursor")


class UnreadSummarySerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Unread, non-archived notifications the user can see.")
    direct_count = serializers.IntegerField(
        help_text="Of those, how many were sent to the user by name or through one of their roles."
    )
    has_critical = serializers.BooleanField(help_text="Whether any of those has `critical` priority.")


class UpdatedCountSerializer(serializers.Serializer):
    updated = serializers.IntegerField(help_text="How many notifications changed.")


class ArchiveAllResponseSerializer(UpdatedCountSerializer):
    notification_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="IDs of the notifications this call archived, for an undo."
    )


class BulkNotificationIdsRequestSerializer(serializers.Serializer):
    notification_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=BULK_NOTIFICATION_IDS_MAX,
        help_text=(
            f"UUIDs of notification events to mark in bulk (max {BULK_NOTIFICATION_IDS_MAX}). "
            "Events the user is not a recipient of are silently skipped."
        ),
    )


class UnarchiveRequestSerializer(serializers.Serializer):
    mark_unread = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Also mark the notifications unread, to restore their state before the archive.",
    )


class BulkUnarchiveRequestSerializer(BulkNotificationIdsRequestSerializer, UnarchiveRequestSerializer):
    pass
