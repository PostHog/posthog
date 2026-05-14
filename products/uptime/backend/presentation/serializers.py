from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    DailyBucketDTO,
    IncidentDTO,
    MonitorDTO,
    MonitorSummaryDTO,
    OutageDTO,
    PingDTO,
    PublicStatusPageDTO,
    StatusPageDTO,
    SuggestedUrlDTO,
)


class MonitorSerializer(DataclassSerializer):
    class Meta:
        dataclass = MonitorDTO


class DailyBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = DailyBucketDTO


class MonitorSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = MonitorSummaryDTO


class CreateMonitorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, help_text="HTTP(S) URL to ping every minute.")


class UpdateMonitorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, help_text="New human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, required=False, help_text="New HTTP(S) URL to ping every minute.")


class ReorderMonitorsSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="Monitor IDs in their desired display order. Position 0 renders first.",
    )


class BulkCreateMonitorItemSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, help_text="HTTP(S) URL to ping every minute.")


class BulkCreateMonitorSerializer(serializers.Serializer):
    monitors = BulkCreateMonitorItemSerializer(
        many=True,
        allow_empty=False,
        help_text="List of monitors to create. All-or-nothing: created atomically.",
    )


class SuggestedUrlSerializer(DataclassSerializer):
    class Meta:
        dataclass = SuggestedUrlDTO


class PingSerializer(DataclassSerializer):
    class Meta:
        dataclass = PingDTO


class OutageSerializer(DataclassSerializer):
    class Meta:
        dataclass = OutageDTO


class StatusPageSerializer(DataclassSerializer):
    class Meta:
        dataclass = StatusPageDTO


class PublicStatusPageSerializer(DataclassSerializer):
    class Meta:
        dataclass = PublicStatusPageDTO


class IncidentSerializer(DataclassSerializer):
    class Meta:
        dataclass = IncidentDTO


class CreateIncidentSerializer(serializers.Serializer):
    monitor_id = serializers.UUIDField(help_text="ID of the monitor this incident is attached to.")
    name = serializers.CharField(max_length=255, help_text="Short, human-readable incident title.")
    description = serializers.CharField(
        required=False, allow_blank=True, help_text="Longer description of the incident, shown publicly."
    )
    started_at = serializers.DateTimeField(
        required=False,
        help_text="When the incident started. Defaults to the time the incident was created.",
    )
    resolved_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the incident was resolved. Omit or null for an ongoing incident.",
    )
    resolution_note = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Resolution note. Required when resolved_at is set.",
    )

    def validate(self, attrs: dict) -> dict:
        if attrs.get("resolved_at") and not attrs.get("resolution_note", "").strip():
            raise serializers.ValidationError(
                {"resolution_note": "A resolution note is required when resolved_at is set."}
            )
        return attrs


class UpdateIncidentSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, help_text="Updated incident title.")
    description = serializers.CharField(
        required=False, allow_blank=True, help_text="Updated description of the incident."
    )
    started_at = serializers.DateTimeField(required=False, help_text="Updated start time of the incident.")
    resolved_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the incident was resolved. Null means the incident is still ongoing.",
    )
    resolution_note = serializers.CharField(
        required=False, allow_blank=True, help_text="Note explaining how the incident was resolved."
    )


class ResolveIncidentSerializer(serializers.Serializer):
    resolution_note = serializers.CharField(
        help_text="Required note explaining how the incident was resolved. Shown on the public status page."
    )


class UpdateStatusPageSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Human-readable title of the status page, shown publicly above the monitor list.",
    )
    slug = serializers.CharField(
        max_length=64,
        required=False,
        help_text="URL slug used in the public URL /status/<slug>. Must be globally unique.",
    )
    monitor_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Ordered list of monitor IDs to display on this status page. Order is preserved.",
    )
