from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    DailyBucketDTO,
    MonitorDTO,
    MonitorSummaryDTO,
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
    url = serializers.URLField(max_length=2048, help_text="HTTP(S) URL to ping every 5 minutes.")


class UpdateMonitorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, help_text="New human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, required=False, help_text="New HTTP(S) URL to ping every 5 minutes.")


class ReorderMonitorsSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="Monitor IDs in their desired display order. Position 0 renders first.",
    )


class BulkCreateMonitorItemSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, help_text="HTTP(S) URL to ping every 5 minutes.")


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


class StatusPageSerializer(DataclassSerializer):
    class Meta:
        dataclass = StatusPageDTO


class PublicStatusPageSerializer(DataclassSerializer):
    class Meta:
        dataclass = PublicStatusPageDTO


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
